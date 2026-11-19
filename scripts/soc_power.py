"""Sample the SK-AM62B's on-board INA power monitors (SPRUJ40F Table 2-19, all 10 mOhm shunts) while a command runs.

    python3 soc_power.py --seconds 20                       # idle
    python3 soc_power.py --seconds 20 -- python3 bench_models.py arti-v0.onnx --runs 400 --threads 1

Prints one JSON line: mean watts per rail and in total, sample count. These are the AM62x SoC rails only (core, DDR,
I/O), not the whole board (USB hub, Ethernet PHY, HDMI bridge, regulators); a USB meter at J11 gives the whole board.
"""
import argparse, fcntl, json, os, subprocess, sys, time

RAILS = {0x40: "VDD_CORE", 0x41: "VDDR_CORE", 0x4C: "DVDD3V3", 0x45: "DVDD1V8", 0x4D: "VDDA_1V8", 0x47: "VDD_DDR4"}
SHUNT_OHM, SHUNT_LSB, BUS_LSB = 0.010, 2.5e-6, 1.25e-3     # INA226/INA231: 2.5 uV and 1.25 mV per bit
I2C_SLAVE_FORCE = 0x0706


def read_reg(fd, addr, reg):
    fcntl.ioctl(fd, I2C_SLAVE_FORCE, addr)
    os.write(fd, bytes([reg]))
    b = os.read(fd, 2)
    v = (b[0] << 8) | b[1]
    return v - 65536 if reg == 0x01 and v & 0x8000 else v


def sample(fd):
    out = {}
    for a, name in RAILS.items():
        vs = read_reg(fd, a, 0x01) * SHUNT_LSB
        vb = read_reg(fd, a, 0x02) * BUS_LSB
        out[name] = vb * vs / SHUNT_OHM
    return out


def main():
    argv = sys.argv[1:]
    cmd = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=float, default=20)
    p.add_argument("--label", default="")
    a = p.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    fd = os.open("/dev/i2c-1", os.O_RDWR)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) if cmd else None
    time.sleep(1.0)                                         # skip model load
    sums, n, t0 = {k: 0.0 for k in RAILS.values()}, 0, time.time()
    while time.time() - t0 < a.seconds and (proc is None or proc.poll() is None):
        for k, v in sample(fd).items():
            sums[k] += v
        n += 1
        time.sleep(0.05)
    out = proc.communicate()[0].strip() if proc else ""
    mean = {k: round(v / max(n, 1), 4) for k, v in sums.items()}
    print(json.dumps(dict(label=a.label, samples=n, total_w=round(sum(mean.values()), 4), rails_w=mean, cmd_out=out[-300:])))


if __name__ == "__main__":
    main()
