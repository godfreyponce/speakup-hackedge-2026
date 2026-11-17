"""Export the wav2vec2 phoneme model #2 times against Arti to ONNX, fp32 and dynamic int8.

Laptop only. Run from the repo root:

    uv run --managed-python --python 3.12 --with torch --with transformers --with onnx --with onnxscript \
        --with onnxruntime --with numpy --with huggingface_hub python scripts/export_wav2vec2.py

It writes models/wav2vec2-lv60-espeak.onnx (with its .data file) and
models/wav2vec2-lv60-espeak-int8.onnx, then prints the IPA each one hears in
recordings/rabbit-say.wav, as a check that the export still works.
"""

import json
import sys
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from huggingface_hub import hf_hub_download
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import Wav2Vec2ForCTC

REPO = "facebook/wav2vec2-lv-60-espeak-cv-ft"
FP32 = Path("models/wav2vec2-lv60-espeak.onnx")
INT8 = Path("models/wav2vec2-lv60-espeak-int8.onnx")
CLIP = Path("recordings/rabbit-say.wav")


class Logits(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, input_values):
        return self.model(input_values).logits


def clip_values():
    with wave.open(str(CLIP), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
    # The model's feature extractor normalizes each clip to zero mean, unit variance.
    return ((x - x.mean()) / np.sqrt(x.var() + 1e-7))[None, :]


def decode(ids, vocab):
    words = {i: t for t, i in vocab.items()}
    out, last = [], None
    for i in ids:
        if i != last and i != vocab["<pad>"]:
            out.append(words[i])
        last = i
    return "".join(out)


def main():
    FP32.parent.mkdir(exist_ok=True)
    model = Logits(Wav2Vec2ForCTC.from_pretrained(REPO).eval())
    torch.onnx.export(
        model, (torch.zeros(1, 16000),), str(FP32), input_names=["input_values"], output_names=["logits"],
        opset_version=18, dynamic_shapes={"input_values": {1: torch.export.Dim("samples", min=400)}},
        dynamo=True, external_data=True,
    )
    # MatMul only: the positional conv's weight is computed by weight norm, so the quantizer can't take Conv.
    quantize_dynamic(str(FP32), str(INT8), weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul"])

    vocab = json.loads(Path(hf_hub_download(REPO, "vocab.json")).read_text(encoding="utf-8"))
    x = clip_values()
    for path in (FP32, INT8):
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        logits = sess.run(["logits"], {"input_values": x})[0]
        print(f"{path}: {decode(logits[0].argmax(-1).tolist(), vocab)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
