import os
import tempfile
import unittest
from pathlib import Path

from speakup.recorder import ArecordRecorder, FakeRecorder, RecorderError


class RecorderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def stub(self, body: str) -> str:
        """A stand-in arecord, so the subprocess call is tested without a mic."""
        path = self.tmp / "arecord"
        path.write_text("#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return str(path)

    def test_arecord_writes_clip_with_16k_mono(self):
        command = self.stub('for last; do :; done; echo "$@" > "$last"')
        clip = self.tmp / "sub" / "clip.wav"
        ArecordRecorder(seconds=3, device="plughw:1,0", command=command).record(clip)
        args = clip.read_text()
        for expected in ["-r 48000", "-c 1", "-f S16_LE", "-d 3", "-D plughw:1,0"]:
            self.assertIn(expected, args)

    def test_arecord_failure_raises_with_stderr(self):
        command = self.stub('echo "no such device" >&2; exit 1')
        with self.assertRaises(RecorderError) as caught:
            ArecordRecorder(seconds=3, command=command).record(self.tmp / "clip.wav")
        self.assertIn("no such device", str(caught.exception))

    def test_missing_command_raises(self):
        with self.assertRaises(RecorderError):
            ArecordRecorder(seconds=3, command="/nonexistent/arecord").record(self.tmp / "clip.wav")

    def test_fake_recorder_writes_nothing(self):
        clip = self.tmp / "clip.wav"
        FakeRecorder().record(clip)
        self.assertFalse(clip.exists())

    def test_sample_clip_goes_to_the_first_word_only(self):
        sample = self.tmp / "rabbit.wav"
        sample.write_bytes(b"RIFF")
        rec = FakeRecorder(sample=sample)
        rec.record(self.tmp / "1.wav")
        rec.record(self.tmp / "2.wav")
        self.assertEqual((self.tmp / "1.wav").read_bytes(), b"RIFF")
        self.assertFalse((self.tmp / "2.wav").exists())


if __name__ == "__main__":
    unittest.main()


class GateTest(unittest.TestCase):
    def run_gate(self, peaks, **kw):
        from speakup.recorder import Gate
        g = Gate(**kw)
        states = []
        for p in peaks:  # the recorder stops reading once the gate says done or silent
            states.append(g.feed(p))
            if states[-1] in ("done", "silent"):
                break
        return g, states

    def test_quiet_room_then_word_then_silence_ends(self):
        peaks = [100] * 15 + [300] * 20 + [6000] * 25 + [200] * 100
        g, states = self.run_gate(peaks)
        self.assertEqual(states[-1], "done")
        self.assertEqual(len(states), 35 + 25 + 100)  # 2 s of quiet ends it
        first, last = g.keep()
        self.assertEqual(first, 35 - 15)  # 0.3 s of lead before the word at frame 35
        self.assertEqual(last, 35 + 25 + 20)  # 0.4 s after the last loud frame, not the whole 2 s of quiet

    def test_ends_at_two_seconds_of_quiet_not_before(self):
        g, states = self.run_gate([100] * 15 + [6000] * 25 + [200] * 95)  # 1.9 s quiet
        self.assertEqual(states[-1], "voice")
        g, states = self.run_gate([100] * 15 + [6000] * 25 + [200] * 100)  # 2.0 s
        self.assertEqual(states[-1], "done")
        self.assertEqual(states[:-1].count("done"), 0)

    def test_a_quiet_child_is_waited_for(self):
        # Nov 12: a shy child is not cut off at 8 s; the gate waits up to 2 minutes for a voice.
        g, states = self.run_gate([100] * 15 + [200] * 1000 + [6000] * 20 + [200] * 100)
        self.assertNotIn("silent", states)
        self.assertEqual(states[-1], "done")
        self.assertTrue(g.heard)

    def test_small_noise_never_starts(self):
        g, states = self.run_gate([100] * 15 + [1500] * 400, wait=5.0)
        self.assertNotIn("voice", states)
        self.assertEqual(states[-1], "silent")

    def test_noisy_room_raises_the_bar(self):
        # Background at 1,000: 2,500 is under 3x and does not start; 5,000 does.
        g, states = self.run_gate([1000] * 15 + [2500] * 10 + [5000] * 3)
        self.assertEqual(states[15:25], ["waiting"] * 10)
        self.assertEqual(states[25], "voice")

    def test_speaking_during_the_calibration_still_starts(self):
        # The child starts 0.1 s after Record: the room is read from its quiet frames, not from the voice.
        g, states = self.run_gate([100] * 5 + [3000] * 30 + [200] * 150)
        self.assertIn("voice", states)
        self.assertEqual(states[-1], "done")

    def test_pause_inside_a_sentence_does_not_end_it(self):
        # A 1.5 s pause between words keeps recording; the 2 s after the last word ends it.
        g, states = self.run_gate([100] * 15 + [6000] * 20 + [200] * 75 + [6000] * 20 + [200] * 100)
        self.assertNotIn("done", states[:-1])
        self.assertEqual(states[-1], "done")
        self.assertEqual(len(states), 15 + 20 + 75 + 20 + 100)

    def test_longest_is_thirty_seconds_by_default(self):
        g, states = self.run_gate([100] * 15 + [6000] * 2000)
        self.assertEqual(states[-1], "done")
        self.assertEqual(len(states), 15 + 1500)

    def test_stop_mid_voice_keeps_the_frames_so_far(self):
        from speakup.recorder import Gate, run_gate
        size = 4
        chunks = iter([bytes([0, 1, 0, 1])] * 15 + [bytes([0x70, 0x17, 0x70, 0x17])] * 30 + [b""])
        frames = []
        calls = {"n": 0}

        def stopping():
            calls["n"] += 1
            return calls["n"] > 40  # the SLP presses Stop after 40 frames, mid-word

        g = Gate()
        state = run_gate(g, lambda: next(chunks), size, stopping, frames)
        self.assertEqual(state, "stopped")
        self.assertEqual(len(frames), 40)
        first, last = g.keep()
        self.assertEqual((first, last), (0, 40))  # the lead and everything up to the Stop

    def test_stop_before_any_voice_keeps_what_was_heard(self):
        from speakup.recorder import Gate
        g, states = self.run_gate([100] * 50)
        self.assertEqual(g.keep(), (15, 50))  # everything after the 0.3 s room calibration

    def test_fake_recorder_stop_ends_the_wait(self):
        import threading
        import time
        rec = FakeRecorder(seconds=5)
        threading.Timer(0.1, rec.request_stop).start()
        began = time.monotonic()
        rec.record(Path(tempfile.gettempdir()) / "never-written.wav")
        self.assertLess(time.monotonic() - began, 2)
        rec.seconds = 0.05  # the same recorder: the flag is cleared for the next recording
        began = time.monotonic()
        rec.record(Path(tempfile.gettempdir()) / "never-written.wav")
        self.assertGreaterEqual(time.monotonic() - began, 0.04)

    def test_longest_cuts_a_long_clip(self):
        g, states = self.run_gate([100] * 15 + [6000] * 500, longest=2.0)
        self.assertEqual(states[-1], "done")
        self.assertEqual(len(states), 15 + 100)
