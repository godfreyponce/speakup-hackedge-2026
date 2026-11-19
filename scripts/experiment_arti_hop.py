"""Arti v2 with a finer time grid: log-mel hop of 5 ms instead of 10 ms (296 frames per 1.5 s instead of 148).

Same BC-ResNet body (fully convolutional with a global mean, so it takes the longer input as is), same data,
seed and scoring as experiment_arti_v2.py. Features are cached separately in arti-cache-hop80/.

    python -I scripts/experiment_arti_hop.py data/percept-r/PERCEPT-R.zip --seed 2028 --out models/arti-v2-hop80.onnx
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import experiment_arti_v2 as v2
from scripts import train_arti as t

# Module level, so the spawned cache workers (which re-import this file) use the same hop.
t.HOP = 80
_build_cache = t.build_cache
t.build_cache = lambda zip_path, clips, cache: _build_cache(zip_path, clips, cache.with_name(cache.name + "-hop80"))

if __name__ == "__main__":
    sys.exit(v2.main())
