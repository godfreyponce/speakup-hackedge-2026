import re
import tempfile
import unittest
from pathlib import Path

from speakup import proof

# llama-completion 0.8.0 (build 11960) on the laptop, run with llm.py's flags, Nov 14.
LLAMA_NEW = """\
0.00.555.125 I common_perf_print:    sampling time =       4.28 ms
0.00.555.127 I common_perf_print:    samplers time =       2.35 ms /    30 tokens
0.00.555.127 I common_perf_print:        load time =     168.65 ms
0.00.555.128 I common_perf_print: prompt eval time =      32.85 ms /     6 tokens (    5.48 ms per token,   182.64 tokens per second)
0.00.555.129 I common_perf_print:        eval time =     168.75 ms /    23 runs   (    7.34 ms per token,   136.30 tokens per second)
0.00.555.140 I common_perf_print:       total time =     206.46 ms /    29 tokens
"""
# The older llama.cpp builds print the same numbers under llama_perf_context_print.
LLAMA_OLD = """\
llama_perf_sampler_print:    sampling time =       9.11 ms /    96 runs   (    0.09 ms per token, 10537.87 tokens per second)
llama_perf_context_print:        load time =    1204.33 ms
llama_perf_context_print: prompt eval time =    9519.02 ms /   203 tokens (   46.89 ms per token,    21.33 tokens per second)
llama_perf_context_print:        eval time =   14301.50 ms /    95 runs   (  150.54 ms per token,     6.64 tokens per second)
llama_perf_context_print:       total time =   23850.10 ms /   298 tokens
"""
# A call whose generation speed llama.cpp could not work out: it prints -nan (or inf) in place of a number.
LLAMA_NAN_EVAL = """\
llama_perf_context_print: prompt eval time =    9519.02 ms /   203 tokens (   46.89 ms per token,    21.33 tokens per second)
llama_perf_context_print:        eval time =       0.00 ms /     0 runs   (     -nan ms per token,     -nan tokens per second)
"""

MEMINFO = """\
MemTotal:        1992768 kB
MemFree:          801232 kB
MemAvailable:    1160960 kB
Buffers:           20480 kB
Cached:           401408 kB
"""

ROUTE_HEADER = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
ROUTE_ONLINE = ROUTE_HEADER + (
    "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
    "eth0\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n")
ROUTE_LAN_ONLY = ROUTE_HEADER + "eth0\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n"
IPV6_LO_REJECT = ("00000000000000000000000000000000 00 00000000000000000000000000000000 00 "
                  "00000000000000000000000000000000 ffffffff 00000001 00000001 00200200 lo\n")
IPV6_DEFAULT = ("00000000000000000000000000000000 00 00000000000000000000000000000000 00 "
                "fe800000000000000000000000000001 00000400 00000001 00000000 00450003 wlan0\n")


class LlamaSpeedsTest(unittest.TestCase):
    def test_new_build(self):
        self.assertEqual(proof.llama_speeds(LLAMA_NEW), (136.30, 182.64))

    def test_old_build(self):
        self.assertEqual(proof.llama_speeds(LLAMA_OLD), (6.64, 21.33))

    def test_no_timing_lines(self):
        self.assertEqual(proof.llama_speeds("loading model\n"), (None, None))

    def test_inf_is_not_a_speed(self):
        text = "llama_perf_context_print:        eval time =       0.00 ms /     1 runs   (    0.00 ms per token,      inf tokens per second)\n"
        self.assertEqual(proof.llama_speeds(text), (None, None))

    def test_nan_is_not_a_speed(self):
        self.assertEqual(proof.llama_speeds(LLAMA_NAN_EVAL), (None, 21.33))


class MeminfoTest(unittest.TestCase):
    def test_used_and_total(self):
        # used = MemTotal - MemAvailable, in kB
        self.assertEqual(proof.meminfo(MEMINFO), (1992768 - 1160960, 1992768))

    def test_missing_field(self):
        self.assertIsNone(proof.meminfo("MemTotal:  1992768 kB\n"))


class RouteTest(unittest.TestCase):
    def test_default_route_is_online(self):
        self.assertTrue(proof.default_route(ROUTE_ONLINE, ""))

    def test_lan_only_is_offline(self):
        self.assertFalse(proof.default_route(ROUTE_LAN_ONLY, IPV6_LO_REJECT))

    def test_down_default_route_is_offline(self):
        self.assertFalse(proof.default_route(ROUTE_HEADER + "eth0\t00000000\t0101A8C0\t0002\t0\t0\t100\t00000000\t0\t0\t0\n", ""))

    def test_unreachable_default_route_is_offline(self):
        self.assertFalse(proof.default_route(ROUTE_HEADER + "*\t00000000\t00000000\t0201\t0\t0\t0\t00000000\t0\t0\t0\n", ""))

    def test_ipv6_default_route_is_online(self):
        self.assertTrue(proof.default_route(ROUTE_LAN_ONLY, IPV6_DEFAULT))


class WattsTest(unittest.TestCase):
    def test_number_kept_as_typed(self):
        p = proof.Proof()
        self.assertIsNone(p.set_watts(" 3.40 "))
        self.assertEqual(p.snapshot().watts, "3.40")

    def test_blank_clears(self):
        p = proof.Proof()
        p.set_watts("3.4")
        self.assertIsNone(p.set_watts(""))
        self.assertIsNone(p.snapshot().watts)

    def test_trailing_point_is_taken_as_the_number(self):
        p = proof.Proof()
        self.assertIsNone(p.set_watts("5."))
        self.assertEqual(p.snapshot().watts, "5")

    def test_rejects_non_numbers(self):
        p = proof.Proof()
        for bad in ("abc", "-2", "0", "nan", "inf", "1e999", ".", "5..", "0."):
            with self.subTest(bad=bad):
                self.assertIsNotNone(p.set_watts(bad))
                self.assertIsNone(p.snapshot().watts)


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = Path(self.dir.name)
        self.meminfo, self.route, self.ipv6 = d / "meminfo", d / "route", d / "ipv6_route"

    def proof(self):
        return proof.Proof(meminfo_path=self.meminfo, route_path=self.route, ipv6_route_path=self.ipv6)

    def test_nothing_measured_yet(self):
        s = self.proof().snapshot()
        self.assertIsNone(s.arti_last_ms)
        self.assertIsNone(s.arti_median_ms)
        self.assertEqual(s.arti_words, 0)
        self.assertIsNone(s.qwen_tps)
        self.assertIsNone(s.qwen_prompt_tps)
        self.assertIsNone(s.watts)
        # no /proc files here: the machine has no /proc, so RAM and network say so
        self.assertIsNone(s.ram_kb)
        self.assertIsNone(s.online)

    def test_measured(self):
        self.meminfo.write_text(MEMINFO)
        self.route.write_text(ROUTE_LAN_ONLY)
        self.ipv6.write_text(IPV6_LO_REJECT)
        p = self.proof()
        for ms in (70.0, 50.0, 61.0):
            p.add_arti_ms(ms)
        p.add_llama_log(LLAMA_OLD)
        s = p.snapshot()
        self.assertEqual((s.arti_last_ms, s.arti_median_ms, s.arti_words), (61.0, 61.0, 3))
        self.assertEqual((s.qwen_tps, s.qwen_prompt_tps), (6.64, 21.33))
        self.assertEqual(s.ram_kb, (1992768 - 1160960, 1992768))
        self.assertIs(s.online, False)

    def test_route_without_ipv6_file(self):
        self.route.write_text(ROUTE_ONLINE)
        self.assertIs(self.proof().snapshot().online, True)

    def test_llama_log_without_timings_keeps_last_speeds(self):
        p = self.proof()
        p.add_llama_log(LLAMA_NEW)
        p.add_llama_log("nothing here\n")
        self.assertEqual(p.snapshot().qwen_tps, 136.30)

    def test_nan_speed_keeps_the_last_real_speeds(self):
        p = self.proof()
        p.add_llama_log(LLAMA_NEW)
        p.add_llama_log(LLAMA_NAN_EVAL)
        s = p.snapshot()
        self.assertEqual((s.qwen_tps, s.qwen_prompt_tps), (136.30, 182.64))

    def test_nan_speed_with_nothing_before_stays_empty(self):
        p = self.proof()
        p.add_llama_log(LLAMA_NAN_EVAL)
        s = p.snapshot()
        self.assertEqual((s.qwen_tps, s.qwen_prompt_tps), (None, None))

    def test_new_session_clears_arti_only(self):
        p = self.proof()
        p.add_arti_ms(60.0)
        p.add_llama_log(LLAMA_NEW)
        p.set_watts("3.4")
        p.new_session()
        s = p.snapshot()
        self.assertEqual((s.arti_last_ms, s.arti_words), (None, 0))
        self.assertEqual((s.qwen_tps, s.watts), (136.30, "3.4"))

    def test_arti_timer_records_ms(self):
        p = self.proof()
        with p.arti_timer():
            pass
        s = p.snapshot()
        self.assertEqual(s.arti_words, 1)
        self.assertLess(s.arti_last_ms, 50)

    def test_arti_timer_skips_a_failed_call(self):
        p = self.proof()
        with self.assertRaises(RuntimeError), p.arti_timer():
            raise RuntimeError("model failed")
        self.assertEqual(p.snapshot().arti_words, 0)

    def test_peak_rss_is_measured(self):
        self.assertGreater(self.proof().snapshot().peak_rss_kb, 1000)


NOTHING = proof.Snapshot(None, None, 0, None, None, None, None, None, None)
MEASURED = proof.Snapshot(61.0, 64.0, 12, 6.64, 21.33, (831808, 1992768), 219136, False, "3.4")


def tiles(snapshot):
    """The bar's markup without its style and script."""
    return proof.bar_html(snapshot).split("<footer")[1].split("</footer>")[0]


def tile_count(html):
    return len(re.findall(r'class="tile[ "]', html))


class BarTest(unittest.TestCase):
    def test_nothing_measured_folds_to_one_line(self):
        html = tiles(NOTHING)
        self.assertEqual(tile_count(html), 0)
        self.assertNotIn('class="big"', html)
        self.assertEqual(html.count('class="unmeasured"'), 1)
        line = html.split('class="unmeasured"')[1]
        for name in ("Arti", "Qwen", "Memory", "Network"):
            self.assertIn(name, line)
        self.assertIn("no usable /proc/meminfo on this machine", line)
        self.assertIn("no /proc/net/route on this machine", line)
        self.assertIn('name="watts" value=""', line)  # the meter can still be typed in

    def test_partly_measured(self):
        html = tiles(proof.Snapshot(61.0, 61.0, 1, None, None, None, 32000, None, None))
        self.assertEqual(tile_count(html), 1)
        self.assertIn("61<span>ms</span>", html)
        line = html.split('class="unmeasured"')[1]
        self.assertNotIn("Arti", line)
        self.assertIn("Qwen", line)
        self.assertIn("app peak 31 MB", line)  # measured, so it stays visible beside the missing total
        self.assertIn('name="watts" value=""', line)

    def test_watts_typed_beside_another_tile_is_a_tile(self):
        html = tiles(proof.Snapshot(None, None, 0, None, None, None, None, True, "3.4"))
        self.assertEqual(tile_count(html), 2)
        self.assertIn('name="watts" value="3.4"', html.split('class="unmeasured"')[0])

    def test_watts_typed_alone_stays_in_the_quiet_line(self):
        html = tiles(proof.Snapshot(None, None, 0, None, None, None, None, None, "3.4"))
        self.assertEqual(tile_count(html), 0)  # a tile of its own would add a row to the folded bar
        self.assertIn('name="watts" value="3.4"', html.split('class="unmeasured"')[1])

    def test_measured(self):
        html = tiles(MEASURED)
        self.assertNotIn("not measured yet", html)
        self.assertNotIn('class="unmeasured"', html)
        self.assertEqual(tile_count(html), 5)
        self.assertIn("61<span>ms</span>", html)
        self.assertIn("median 64 ms over 12 tries this session", html)
        self.assertIn("6.6<span>tokens/s</span>", html)
        self.assertIn("prompt 21.3 tokens/s", html)
        self.assertIn("812<span>of 1,946 MB</span>", html)
        self.assertIn("app peak 214 MB, main process", html)
        self.assertIn('<div class="big">Offline</div>', html)
        self.assertIn('name="watts" value="3.4"', html)

    def test_online(self):
        html = tiles(proof.Snapshot(None, None, 0, None, None, None, None, True, None))
        self.assertIn('<div class="big">Online</div>', html)

    def test_generation_speed_without_prompt_speed(self):
        html = tiles(proof.Snapshot(None, None, 0, 6.64, None, None, None, None, None))
        self.assertIn("6.6<span>tokens/s</span>", html)
        self.assertNotIn("prompt", html)


if __name__ == "__main__":
    unittest.main()
