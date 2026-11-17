"""Checks for the #19 masking experiment. Needs the laptop ML set; skipped without it."""

import contextlib
import io
import json
import pickle
import statistics
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

try:
    import numpy as np
    import onnxruntime  # noqa: F401
    import torch
    import torchaudio  # noqa: F401
except ImportError as e:
    raise unittest.SkipTest(f"needs the laptop ML set: {e}")

from scripts import experiment_arti, train_arti


def _data(n_train=48, n_val=16, frames=148):
    rng = np.random.default_rng(0)
    n = n_train + n_val
    labels = np.array([i % 2 for i in range(n)], dtype=np.int64)
    mels = rng.standard_normal((n, train_arti.N_MELS, frames)).astype(np.float32)
    mels += labels[:, None, None]
    is_val = np.array([i >= n_train for i in range(n)])
    return mels.astype(np.float16), labels, is_val


def _train(*args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return train_arti.train(*args, **kwargs)


class TrainTest(unittest.TestCase):
    def test_returns_best_epoch_and_val_predictions(self):
        mels, labels, is_val = _data()
        body, epoch, pred = _train(mels, labels, is_val, "cpu")
        self.assertIsInstance(body, train_arti.Body)
        self.assertTrue(1 <= epoch <= train_arti.EPOCHS)
        self.assertEqual(pred.shape, (16,))
        self.assertTrue(set(pred.tolist()) <= {0, 1})

    def test_augment_sees_float32_training_batches_only(self):
        mels, labels, is_val = _data()
        mels[is_val] = 1000.0
        seen = []

        def spy(batch):
            seen.append(batch)
            return batch

        _train(mels, labels, is_val, "cpu", augment=spy)
        self.assertTrue(all(b.dtype == torch.float32 for b in seen))
        self.assertFalse(any((b == 1000.0).any() for b in seen))
        self.assertEqual(sum(len(b) for b in seen), 48 * train_arti.EPOCHS)

    def test_mels_not_mutated(self):
        mels, labels, is_val = _data()
        before = mels.copy()
        _train(mels, labels, is_val, "cpu", augment=lambda b: b.clone().fill_(0))
        self.assertTrue(np.array_equal(mels, before))

    def test_same_seed_and_order_give_same_run(self):
        mels, labels, is_val = _data()
        g = torch.Generator().manual_seed(3)

        def draws(batch):
            torch.rand(len(batch), generator=g)
            return batch.clone()

        a = _train(mels, labels, is_val, "cpu", seed=7, order=torch.Generator().manual_seed(8))
        b = _train(mels, labels, is_val, "cpu", seed=7, order=torch.Generator().manual_seed(8), augment=draws)
        for key, value in a[0].state_dict().items():
            self.assertTrue(torch.equal(value, b[0].state_dict()[key]), key)
        self.assertEqual(a[1], b[1])
        self.assertTrue(np.array_equal(a[2], b[2]))

    def test_different_seed_gives_different_init(self):
        mels, labels, is_val = _data()
        a = _train(mels, labels, is_val, "cpu", seed=7, order=torch.Generator().manual_seed(8))
        b = _train(mels, labels, is_val, "cpu", seed=9, order=torch.Generator().manual_seed(8))
        self.assertFalse(all(torch.equal(v, b[0].state_dict()[k]) for k, v in a[0].state_dict().items()))


class MaskTest(unittest.TestCase):
    def setUp(self):
        self.x = torch.randn(2000, train_arti.N_MELS, 148, generator=torch.Generator().manual_seed(0))

    def _check_band(self, axis, max_width, size):
        out = experiment_arti.mask(self.x, axis, max_width, torch.Generator().manual_seed(1))
        changed = out != self.x
        line_dim, other_dim = axis - 1, 2 - axis
        widths = set()
        for clip in changed:
            lines = clip.any(dim=other_dim).nonzero().flatten().tolist()
            widths.add(len(lines))
            self.assertLessEqual(len(lines), max_width)
            if lines:
                self.assertEqual(lines[-1] - lines[0] + 1, len(lines))
                self.assertTrue(0 <= lines[0] and lines[-1] < size)
            band = clip.index_select(line_dim, torch.tensor(lines, dtype=torch.long))
            self.assertTrue(band.all())
            self.assertEqual(int(clip.sum()), band.numel())
        self.assertIn(0, widths)
        self.assertIn(max_width, widths)

    def test_time_mask_bounds(self):
        self._check_band(2, experiment_arti.TIME_MAX_FRAMES, 148)

    def test_frequency_mask_bounds(self):
        self._check_band(1, experiment_arti.FREQ_MAX_BINS, train_arti.N_MELS)

    def test_fill_is_clip_mean(self):
        for axis, width in ((1, 2), (2, 5)):
            out = experiment_arti.mask(self.x, axis, width, torch.Generator().manual_seed(1))
            changed = out != self.x
            want = self.x.mean(dim=(1, 2))[:, None, None].expand_as(self.x)
            self.assertTrue(changed.any())
            self.assertTrue(torch.equal(out[changed], want[changed]))

    def test_input_not_mutated(self):
        before = self.x.clone()
        experiment_arti.mask(self.x, 2, 5, torch.Generator().manual_seed(1))
        experiment_arti.mask(self.x, 1, 2, torch.Generator().manual_seed(1))
        self.assertTrue(torch.equal(self.x, before))

    def test_reproducible(self):
        def run(seed):
            return experiment_arti.mask(self.x, 2, 5, torch.Generator().manual_seed(seed))

        self.assertTrue(torch.equal(run(1), run(1)))
        self.assertFalse(torch.equal(run(1), run(2)))

    def test_stream_seeds(self):
        seeds = experiment_arti.stream_seeds(2026)
        self.assertEqual(len(set(seeds)), 3)
        self.assertTrue(all(type(s) is int for s in seeds))
        self.assertEqual(seeds, experiment_arti.stream_seeds(2026))
        self.assertNotEqual(seeds, experiment_arti.stream_seeds(2027))


def _runs(per_method):
    return [{"method": m, "seed": seed, "balanced_accuracy": bacc, "missed_errors": 10, "false_alarms": 20,
             "best_epoch": 5}
            for m, baccs in per_method.items() for seed, bacc in zip(experiment_arti.TRAIN_SEEDS, baccs)]


class SummaryTest(unittest.TestCase):
    def test_rank_by_mean(self):
        rows = experiment_arti.summarize(_runs({
            "baseline": [0.78, 0.77, 0.79], "time": [0.75, 0.74, 0.76], "frequency": [0.80, 0.79, 0.81]}))
        self.assertEqual([r["method"] for r in rows], ["frequency", "baseline", "time"])
        freq = rows[0]
        self.assertEqual(set(freq["paired_difference"]), set(experiment_arti.TRAIN_SEEDS))
        for diff in freq["paired_difference"].values():
            self.assertAlmostEqual(diff, 0.02)
        self.assertAlmostEqual(freq["mean_balanced_accuracy"], 0.80)

    def test_exact_tie_keeps_baseline_first(self):
        same = [0.70, 0.80, 0.75]
        rows = experiment_arti.summarize(_runs({"time": same, "baseline": same, "frequency": [0.1, 0.1, 0.1]}))
        self.assertEqual([r["method"] for r in rows], ["baseline", "time", "frequency"])

    def test_spread(self):
        values = [0.70, 0.80, 0.75]
        rows = experiment_arti.summarize(_runs({"baseline": values, "time": values, "frequency": values}))
        for row in rows:
            self.assertAlmostEqual(row["sd_balanced_accuracy"], statistics.stdev(values))
            self.assertEqual(row["min_balanced_accuracy"], min(values))
            self.assertEqual(row["max_balanced_accuracy"], max(values))
            self.assertEqual(row["per_seed"], dict(zip(experiment_arti.TRAIN_SEEDS, values)))


RECORD_KEYS = {"method", "seed", "init_seed", "order_seed", "mask_seed", "config", "best_epoch",
               "balanced_accuracy", "missed_errors", "false_alarms", "val_counts", "train_counts",
               "train_seconds"}


def _f(x):
    return pickle.dumps(x, protocol=4)


def _make_corpus(folder):
    zip_path = folder / "PERCEPT-R.zip"
    root = "FAKE 1.0py"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for n in range(1, 12):
            sid = str(n)
            zf.writestr(f"{root}/{sid}/metadata/age.pickle", _f(72 + 7 * (n - 1) if n <= 10 else 100))
            for take, label in enumerate((1.0, 1.0, 0.0, 0.0), 1):
                stem = f"{sid}_X_A-1_red_{take}"
                zf.writestr(f"{root}/{sid}/audio/{stem}.wav", b"")
                zf.writestr(f"{root}/{sid}/rhotic_perceptual_labels/{stem}.pickle", _f(label))
    (folder / "test-speakers.txt").write_text("11\n", encoding="utf-8")
    with zipfile.ZipFile(zip_path) as zf:
        clips = train_arti.index(zf, ["11"])[0]
    cache = folder / "arti-cache"
    cache.mkdir()
    (cache / "index.csv").write_text("".join(f"{n},{s},{y}\n" for n, s, y in clips), encoding="utf-8")
    y = np.array([c[2] for c in clips], dtype=np.int64)
    mels = np.random.default_rng(0).standard_normal((len(clips), train_arti.N_MELS, 148)) + y[:, None, None]
    np.save(cache / "mels.npy", mels.astype(np.float16))
    return zip_path


def _snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.folder = Path(tmp.name)
        zip_path = _make_corpus(cls.folder)
        cls.before = _snapshot(cls.folder)
        with mock.patch.object(train_arti, "score", side_effect=AssertionError("score called")), \
                mock.patch.object(train_arti, "export", side_effect=AssertionError("export called")), \
                contextlib.redirect_stdout(io.StringIO()):
            cls.code = experiment_arti.main([str(zip_path), "--device", "cpu"])
        cls.after = _snapshot(cls.folder)
        cls.results = json.loads((cls.folder / "arti-masking" / "results.json").read_text(encoding="utf-8"))

    def test_nine_runs_recorded(self):
        runs = self.results["runs"]
        self.assertEqual(len(runs), 9)
        self.assertEqual({(r["method"], r["seed"]) for r in runs},
                         {(m, s) for m in experiment_arti.METHODS for s in experiment_arti.TRAIN_SEEDS})
        for run in runs:
            self.assertEqual(set(run), RECORD_KEYS)
        self.assertEqual(len(self.results["ranking"]), 3)

    def test_held_out_speaker_excluded(self):
        for run in self.results["runs"]:
            self.assertEqual(sum(run["val_counts"].values()) + sum(run["train_counts"].values()), 40)
        self.assertEqual(self.results["speakers"]["test"], 1)

    def test_split_same_for_every_seed(self):
        self.assertEqual(len({json.dumps(r["val_counts"], sort_keys=True) for r in self.results["runs"]}), 1)

    def test_paired_runs_share_init_and_order(self):
        for seed in experiment_arti.TRAIN_SEEDS:
            runs = [r for r in self.results["runs"] if r["seed"] == seed]
            self.assertEqual(len({(r["init_seed"], r["order_seed"]) for r in runs}), 1)

    def test_outputs_only_in_out_dir(self):
        new = set(self.after) - set(self.before)
        want = {f"arti-masking/{m}-seed{s}.pt" for m in experiment_arti.METHODS for s in experiment_arti.TRAIN_SEEDS}
        self.assertEqual(new, want | {"arti-masking/results.json"})
        for name, data in self.before.items():
            self.assertEqual(self.after[name], data, name)

    def test_score_and_test_set_never_used(self):
        self.assertEqual(self.code, 0)
        self.assertFalse(hasattr(experiment_arti, "score"))
        self.assertFalse(hasattr(experiment_arti, "export"))
