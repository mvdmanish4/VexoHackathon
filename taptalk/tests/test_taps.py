"""Tests for taps.py with synthetic 833-a-second accelerometer traces (no band needed)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from taps import TapClassifier, TapDetector, WristTurn, calibrate  # noqa: E402

RATE = 833.0
REST = (0.0, 0.0, -1.0)          # gravity while the hand rests on a table


def trace(seconds, taps=(), extra=None, noise=0.02):
    """Samples (t, ax, ay, az): resting, plus a sharp ringing jolt at each tap time.
    extra(t) -> (dx, dy, dz) adds slow movement."""
    out = []
    n = int(seconds * RATE)
    for i in range(n):
        t = i / RATE
        x, y, z = REST
        if extra:
            dx, dy, dz = extra(t)
            x, y, z = x + dx, y + dy, z + dz
        for tt, g in taps:
            d = t - tt
            if 0 <= d < 0.04:     # a hit ringing at 150 Hz, gone in ~20 ms
                z += g * math.exp(-d / 0.006) * math.cos(2 * math.pi * 150 * d)
        z += noise * math.sin(i * 1.7)
        out.append((t, x, y, z))
    return out


def detect(samples, **kw):
    found, rejected = [], []
    det = TapDetector(on_tap=lambda t, s: found.append((t, s)),
                      on_reject=lambda t, s, w: rejected.append(w), **kw)
    for s in samples:
        det.feed(*s)
    return found, rejected


class DetectorTest(unittest.TestCase):
    def test_one_ringing_tap_is_one_tap(self):
        found, _ = detect(trace(1, [(0.5, 2.5)]))
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0][0], 0.5, delta=0.01)
        self.assertGreater(found[0][1], 1.5)

    def test_light_tap_below_threshold_is_missed_and_lower_threshold_finds_it(self):
        self.assertEqual(len(detect(trace(1, [(0.5, 0.6)]))[0]), 0)
        self.assertEqual(len(detect(trace(1, [(0.5, 0.6)]), threshold=0.4)[0]), 1)

    def test_two_quick_taps_are_two_taps(self):
        found, _ = detect(trace(1, [(0.3, 2.5), (0.48, 2.5)]))
        self.assertEqual(len(found), 2)
        self.assertAlmostEqual(found[1][0] - found[0][0], 0.18, delta=0.01)

    def test_arm_swing_is_not_a_tap(self):
        def swing(t):
            return (0.6 * math.sin(2 * math.pi * 1.5 * t), 0.4 * math.sin(2 * math.pi * 1.0 * t), 0)
        self.assertEqual(detect(trace(3, extra=swing))[0], [])

    def test_wrist_turn_is_not_a_tap(self):
        def turn(t):                      # gravity swings from -z to +z over 0.3 s
            a = math.pi * min(1, max(0, (t - 0.5) / 0.3))
            return (math.sin(a), 0, 1 - math.cos(a))
        self.assertEqual(detect(trace(2, extra=turn))[0], [])

    def test_long_shove_is_rejected_as_movement(self):
        def shove(t):
            return (0, 0, 1.8 if 0.5 <= t < 0.7 else 0)
        found, rejected = detect(trace(1.5, extra=shove))
        self.assertEqual(found, [])
        self.assertTrue(rejected)


def classify(times, window=0.30):
    out = []
    c = TapClassifier(window, on_dot=lambda t: out.append("."), on_dash=lambda t: out.append("-"))
    events = sorted(times)
    end = events[-1] + 1
    t = 0.0
    while t <= end:
        while events and events[0] <= t:
            c.tap(events.pop(0))
        c.tick(t)
        t += 0.01
    return "".join(out)


class ClassifierTest(unittest.TestCase):
    def test_double_tap_is_one_dash(self):
        self.assertEqual(classify([0.0, 0.18]), "-")

    def test_slow_taps_are_dots(self):
        self.assertEqual(classify([0.0, 0.5]), "..")

    def test_quick_dots_at_0_4_s_stay_dots(self):
        self.assertEqual(classify([0.0, 0.4, 0.8]), "...")

    def test_letters_a_and_n(self):
        self.assertEqual(classify([0.0, 0.5, 0.65]), ".-")          # A
        self.assertEqual(classify([0.0, 0.15, 0.6]), "-.")          # N

    def test_three_quick_taps_are_dash_then_dot(self):
        self.assertEqual(classify([0.0, 0.15, 0.3]), "-.")

    def test_dot_keeps_its_own_tap_time(self):
        got = []
        c = TapClassifier(0.3, on_dot=got.append)
        c.tap(1.0)
        c.tick(1.5)
        self.assertEqual(got, [1.0])

    def test_cancel_forgets_waiting_tap(self):
        got = []
        c = TapClassifier(0.3, on_dot=got.append)
        c.tap(1.0)
        c.cancel()
        c.tick(2.0)
        self.assertEqual(got, [])

    def test_trace_to_symbols(self):
        # N = - .  : a double tap, then a single tap 0.6 s later
        out = []
        c = TapClassifier(0.3, on_dot=lambda t: out.append("."), on_dash=lambda t: out.append("-"))
        det = TapDetector(on_tap=lambda t, s: c.tap(t))
        for s in trace(2, [(0.3, 2.5), (0.47, 2.5), (1.07, 2.5)]):
            det.feed(*s)
            c.tick(s[0])
        self.assertEqual("".join(out), "-.")


class WristTest(unittest.TestCase):
    def run_turn(self, hold_s):
        sent = []
        w = WristTurn(on_send=lambda: sent.append(True))

        def turn(t):
            a = math.pi * min(1, max(0, (t - 1.0) / 0.3))
            if t > 1.3 + hold_s:        # turn back
                a = 0.0
            return (math.sin(a), 0, 1 - math.cos(a))
        for i, s in enumerate(trace(3, extra=turn, noise=0)):
            w.feed(*s)
            if i == 100:
                w.note_tap()             # tapping at home teaches where home is
        return sent

    def test_turn_held_sends_once(self):
        self.assertEqual(self.run_turn(1.0), [True])

    def test_quick_turn_does_not_send(self):
        self.assertEqual(self.run_turn(0.2), [])

    def test_no_home_no_send(self):
        sent = []
        w = WristTurn(on_send=lambda: sent.append(True))
        for s in trace(1, extra=lambda t: (1, 0, 2), noise=0):
            w.feed(*s)
        self.assertEqual(sent, [])


class CalibrateTest(unittest.TestCase):
    def test_window_sits_between_rhythms(self):
        singles = [0, 0.7, 1.35, 2.1, 2.8]
        doubles = []
        for start in (0, 0.9, 1.8, 2.7, 3.6):
            doubles += [start, start + 0.17]
        window, rep = calibrate(singles, doubles)
        self.assertTrue(rep["ok"])
        self.assertGreater(window, 0.19)
        self.assertLess(window, 0.65)
        self.assertAlmostEqual(rep["double_gap"], 0.17, delta=0.01)

    def test_overlap_is_reported(self):
        singles = [0, 0.2, 0.9, 1.6]
        doubles = []
        for start in (0, 1, 2, 3):
            doubles += [start, start + 0.25]
        _, rep = calibrate(singles, doubles)
        self.assertFalse(rep["ok"])
        self.assertIn("more time", rep["why"])

    def test_too_few_taps(self):
        window, rep = calibrate([0, 1], [0, 0.2])
        self.assertIsNone(window)
        self.assertFalse(rep["ok"])


if __name__ == "__main__":
    unittest.main()
