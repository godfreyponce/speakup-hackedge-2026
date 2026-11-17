import contextlib
import io
import unittest
from unittest import mock

from speakup import __main__ as cli


class StartUpTest(unittest.TestCase):
    def run_main(self, *args):
        """main() with these flags; a server it would start raises instead, so no port is bound."""
        stderr = io.StringIO()
        with mock.patch("sys.argv", ["speakup", *args]), \
                mock.patch.object(cli, "make_server", side_effect=AssertionError("start-up went on to the server")), \
                contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as stop:
            cli.main()
        return stop.exception.code, stderr.getvalue()

    def test_refuses_a_rate_under_16000(self):
        code, err = self.run_main("--arecord", "--rate", "8000")
        self.assertEqual(code, 2)
        self.assertIn("--rate", err)


if __name__ == "__main__":
    unittest.main()
