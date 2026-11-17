import unittest
from unittest import mock

from speakup import calibration


class UnsureTest(unittest.TestCase):
    def test_the_band_ships_empty(self):
        self.assertIsNone(calibration.UNSURE_BAND)

    def test_never_unsure_without_a_band(self):
        for p in (0.0, 0.3, 0.5, 0.7, 1.0):
            self.assertFalse(calibration.unsure(p))

    def test_unsure_inside_the_band_ends_included(self):
        with mock.patch.object(calibration, "UNSURE_BAND", (0.4, 0.6)):
            self.assertEqual([calibration.unsure(p) for p in (0.39, 0.4, 0.5, 0.6, 0.61)],
                             [False, True, True, True, False])


if __name__ == "__main__":
    unittest.main()
