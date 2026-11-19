"""Count trainable weights in an ONNX file without the onnx package (parses initializer tensor dims from the protobuf)."""


def _varint(b, i):
    v, s = 0, 0
    while True:
        c = b[i]; i += 1
        v |= (c & 0x7F) << s; s += 7
        if c < 0x80:
            return v, i


def _fields(b):
    i, out = 0, []
    while i < len(b):
        key, i = _varint(b, i)
        f, t = key >> 3, key & 7
        if t == 0:
            v, i = _varint(b, i)
        elif t == 2:
            n, i = _varint(b, i); v = b[i:i + n]; i += n
        elif t == 5:
            v = b[i:i + 4]; i += 4
        elif t == 1:
            v = b[i:i + 8]; i += 8
        else:
            return out
        out.append((f, t, v))
    return out


def count(path):
    """ModelProto.graph (7) -> GraphProto.initializer (5) -> TensorProto.dims (1, packed or repeated)."""
    data = open(path, "rb").read()
    total = 0
    for f, t, g in _fields(data):
        if f != 7 or t != 2:
            continue
        for gf, gt, init in _fields(g):
            if gf != 5 or gt != 2:
                continue
            dims = []
            for tf, tt, tv in _fields(init):
                if tf == 1 and tt == 0:
                    dims.append(tv)
                elif tf == 1 and tt == 2:
                    j = 0
                    while j < len(tv):
                        d, j = _varint(tv, j); dims.append(d)
            n = 1
            for d in dims:
                n *= d
            total += n if dims else 1
    return total
