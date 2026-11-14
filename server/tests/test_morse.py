import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # server/
from helen.morse import TapDecoder, encode  # noqa: E402


def taps(dec, pattern, start=0.0, step=0.4):
    """Feed a pattern like '.-' with `step` seconds between symbols; return the last time."""
    t = start
    for s in pattern:
        dec.dot(t) if s == "." else dec.dash(t)
        t += step
    return t - step


class DecoderTest(unittest.TestCase):
    def setUp(self):
        self.letters, self.messages, self.deletes = [], [], []
        self.words = []
        self.dec = TapDecoder(letter_gap=1.5, word_gap=3.0, send_gap=8.0, adaptive=False,
                              on_letter=self.letters.append, on_message=self.messages.append,
                              on_delete=lambda: self.deletes.append(1), on_word=self.words.append)

    def test_four_dots_is_h(self):
        last = taps(self.dec, "....")
        self.dec.tick(last + 1.0)
        self.assertEqual(self.dec.text, "")          # still inside the letter
        self.dec.tick(last + 1.6)
        self.assertEqual(self.dec.text, "H")
        self.assertEqual(self.letters, ["H"])

    def test_dot_dash_is_a(self):
        last = taps(self.dec, ".-")
        self.dec.tick(last + 2)
        self.assertEqual(self.dec.text, "A")

    def test_word_gap_adds_one_space(self):
        last = taps(self.dec, "..")
        self.dec.tick(last + 2)
        self.dec.tick(last + 3.5)
        self.dec.tick(last + 4.0)
        self.assertEqual(self.dec.text, "I ")
        last = taps(self.dec, "..", start=last + 5)
        self.dec.tick(last + 2)
        self.assertEqual(self.dec.text, "I I")

    def test_unknown_code_is_question_mark(self):
        last = taps(self.dec, "..--..--")
        self.dec.tick(last + 2)
        self.assertEqual(self.dec.text, "?")

    def test_dedup_drops_tap_just_before_double_tap(self):
        dec = TapDecoder(dedup=0.3)
        dec.dot(10.0)
        dec.dash(10.2)            # the band sent "tap" then "double-tap" for one gesture
        dec.tick(12)
        self.assertEqual(dec.text, "T")

    def test_dedup_keeps_a_deliberate_dot(self):
        dec = TapDecoder(dedup=0.3)
        dec.dot(10.0)
        dec.dash(10.5)
        dec.tick(13)
        self.assertEqual(dec.text, "A")

    def test_dedup_off_by_default_keeps_both(self):
        dec = TapDecoder()
        dec.dot(10.0)
        dec.dash(10.2)
        dec.tick(12)
        self.assertEqual(dec.text, "A")

    def test_six_dots_delete_last_letter(self):
        last = taps(self.dec, "...")              # S
        self.dec.tick(last + 2)
        last = taps(self.dec, "......", start=last + 2.5)
        self.dec.tick(last + 2)
        self.assertEqual(self.dec.text, "")
        self.assertEqual(self.deletes, [1])

    def test_send_request_closes_letter_and_sends(self):
        last = taps(self.dec, "...")
        self.dec.tick(last + 2)
        last = taps(self.dec, "---", start=last + 2)
        self.dec.request_send()                   # wrist turned over mid-letter
        self.dec.tick(last + 0.1)
        self.assertEqual(self.messages, ["SO"])
        self.assertEqual(self.dec.text, "")

    def test_auto_send_after_long_pause(self):
        last = taps(self.dec, "....")
        for dt in (2, 4, 9):
            self.dec.tick(last + dt)
        self.assertEqual(self.messages, ["H"])
        self.dec.tick(last + 20)                  # nothing more to send
        self.assertEqual(self.messages, ["H"])

    def test_empty_send_sends_nothing(self):
        self.dec.request_send()
        self.dec.tick(1)
        self.assertEqual(self.messages, [])

    def test_on_word_fires_once_per_word(self):
        last = taps(self.dec, "..")
        for dt in (2, 3.5, 4, 5):
            self.dec.tick(last + dt)
        self.assertEqual(self.words, ["I"])
        last = taps(self.dec, "....", start=last + 5.5)
        for dt in (2, 3.5, 4):
            self.dec.tick(last + dt)
        self.assertEqual(self.words, ["I", "I H"])

    def test_no_word_event_when_sending(self):
        last = taps(self.dec, "..")
        self.dec.request_send()
        self.dec.tick(last + 5)
        self.assertEqual(self.words, [])
        self.assertEqual(self.messages, ["I"])

    def test_fixed_gaps_do_not_change(self):
        taps(self.dec, "....", step=0.2)
        taps(self.dec, "....", start=5, step=0.2)
        self.assertEqual(self.dec.gaps, (1.5, 3.0, 8.0))

    def test_encode(self):
        self.assertEqual(encode("sos hi"), "... --- ... / .... ..")


if __name__ == "__main__":
    unittest.main()


class AdaptiveTest(unittest.TestCase):
    def test_fast_tapper_gets_shorter_pauses(self):
        dec = TapDecoder()
        start = dec.gaps
        t = 0.0
        for _ in range(3):                      # three "H"s tapped 0.25 s apart
            t = taps(dec, "....", start=t, step=0.25) + 1.3
            dec.tick(t)
        letter, word, send = dec.gaps
        self.assertAlmostEqual(letter, 0.75)
        self.assertAlmostEqual(word, 2.2 * 0.75)
        self.assertLess(letter, start[0])
        self.assertEqual(send, 4.0)             # never below the minimum
        self.assertEqual(dec.text, "HHH")

    def test_pauses_stay_in_range(self):
        fast, slow = TapDecoder(), TapDecoder()
        taps(fast, "." * 5 + "-", step=0.05)    # superhuman: clamped at the minimum
        taps(slow, "." * 6, step=1.1)          # slow, but each gap still inside the letter
        self.assertEqual(fast.gaps[0], 0.6)
        self.assertLessEqual(slow.gaps[0], 2.0)

    def test_needs_a_few_gaps_before_adapting(self):
        dec = TapDecoder()
        taps(dec, "...", step=0.2)              # only 2 gaps so far
        self.assertEqual(dec.gaps[0], 1.2)

    def test_letter_gaps_are_not_learned_as_taps(self):
        dec = TapDecoder()
        t = 0.0
        for _ in range(4):                      # "E"s far apart: no gap inside a letter
            dec.dot(t)
            t += 2.0
            dec.tick(t - 0.1)
        self.assertEqual(dec.gaps[0], 1.2)
        self.assertEqual(dec.text.replace(" ", ""), "EEEE")
