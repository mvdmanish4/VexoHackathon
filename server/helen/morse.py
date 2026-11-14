"""Tap Morse decoder: single tap = dot, double tap = dash, pauses end letters and words.

Pure logic with no band and no network, so it can be tested with made-up timestamps.
Times are in seconds (floats), like `time.time()` and the band's `event.time`.

The pauses adapt to the person: after a few letters the decoder knows how fast they tap
and shortens (or lengthens) the letter, word and send pauses to match, like a Morse
operator's 1 : 3 : 7 rhythm.
"""
import statistics
import threading
from collections import deque

MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F", "--.": "G",
    "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L", "--": "M", "-.": "N",
    "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R", "...": "S", "-": "T", "..-": "U",
    "...-": "V", ".--": "W", "-..-": "X", "-.--": "Y", "--..": "Z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4",
    ".....": "5", "-....": "6", "--...": "7", "---..": "8", "----.": "9",
}

# Six or more dots in one letter = "I made a mistake": delete the last letter.
# (Standard Morse uses eight dots for "error"; six is quicker to tap.)
DELETE_MIN_DOTS = 6

# Adaptive pauses: letter gap = 3 x the person's usual gap between taps, kept in this range.
MIN_LETTER_GAP, MAX_LETTER_GAP = 0.6, 2.0
WORD_FACTOR = 2.2          # word gap = this x letter gap
SEND_FACTOR = 4.0          # auto-send gap = this x letter gap, at least MIN_SEND_GAP
MIN_SEND_GAP = 4.0
SAMPLES_NEEDED = 5         # gaps to see before adapting
SAMPLES_KEPT = 12


class TapDecoder:
    """Feed it dots and dashes, call tick() often, read `text`, `current` and `gaps`.

    Callbacks run inside tick(), on the caller's thread, never on the band's thread:
    on_letter(ch) when a letter is finished, on_delete() when the last letter was erased,
    on_word(text) when a word is finished (the text so far), on_message(text) on send.
    """

    def __init__(self, letter_gap=1.2, word_gap=2.6, send_gap=6.0, dedup=0, adaptive=True,
                 on_letter=None, on_delete=None, on_word=None, on_message=None):
        self.letter_gap = letter_gap
        self.word_gap = word_gap
        self.send_gap = send_gap      # 0 or None = no automatic send
        self.dedup = dedup            # seconds; >0 drops a dot this soon before a dash (off by default)
        self.adaptive = adaptive
        self.on_letter = on_letter
        self.on_delete = on_delete
        self.on_word = on_word
        self.on_message = on_message
        self.text = ""
        self.current = ""             # dots and dashes of the letter being tapped
        self._last = None             # time of the last dot or dash
        self._last_dot = None         # time of the last dot, for dedup
        self._send_requested = False
        self._intra = deque(maxlen=SAMPLES_KEPT)   # gaps between taps inside a letter
        self._lock = threading.Lock()

    @property
    def gaps(self):
        """(letter, word, send) pauses in seconds, as used right now."""
        return self.letter_gap, self.word_gap, self.send_gap

    # ---- input: safe to call from the band's handler thread ----

    def dot(self, t):
        with self._lock:
            self._note_gap(t)
            self.current += "."
            self._last = self._last_dot = t

    def dash(self, t):
        with self._lock:
            # Some sensors report a single tap just before the double tap it belongs to.
            if (self.dedup and self._last_dot is not None and self.current.endswith(".")
                    and 0 <= t - self._last_dot <= self.dedup):
                self.current = self.current[:-1]
                if self._intra:
                    self._intra.pop()     # that gap was the sensor, not the person
            else:
                self._note_gap(t)
            self.current += "-"
            self._last = t
            self._last_dot = None

    def request_send(self):
        """Send the message at the next tick (safe from any thread)."""
        with self._lock:
            self._send_requested = True

    def _note_gap(self, t):
        """Learn the person's rhythm from gaps between taps of the same letter."""
        if not (self.adaptive and self.current and self._last is not None):
            return
        gap = t - self._last
        if 0 < gap < self.letter_gap:
            self._intra.append(gap)
            if len(self._intra) >= SAMPLES_NEEDED:
                unit = statistics.median(self._intra)
                self.letter_gap = min(MAX_LETTER_GAP, max(MIN_LETTER_GAP, 3 * unit))
                self.word_gap = WORD_FACTOR * self.letter_gap
                if self.send_gap:
                    self.send_gap = max(MIN_SEND_GAP, SEND_FACTOR * self.letter_gap)

    # ---- driving: called from the main program ----

    def tick(self, now):
        events = []
        message = None
        with self._lock:
            idle = None if self._last is None else now - self._last
            if self.current and (self._send_requested or (idle is not None and idle > self.letter_gap)):
                events.append(self._close_letter())
            if (self.text and not self.text.endswith(" ") and idle is not None
                    and idle > self.word_gap and not self._send_requested):
                self.text += " "
                events.append(("word", self.text.strip()))
            auto = bool(self.send_gap and idle is not None and idle > self.send_gap
                        and self.text.strip())
            if self._send_requested or auto:
                message = self.text.strip() or None
                self.text = ""
                self._send_requested = False
                self._last = None
        for kind, value in events:
            if kind == "letter" and self.on_letter:
                self.on_letter(value)
            elif kind == "delete" and self.on_delete:
                self.on_delete()
            elif kind == "word" and self.on_word:
                self.on_word(value)
        if message and self.on_message:
            self.on_message(message)
        return message

    def _close_letter(self):
        code, self.current = self.current, ""
        self._last_dot = None
        if set(code) == {"."} and len(code) >= DELETE_MIN_DOTS:
            self.text = self.text.rstrip()[:-1]
            return ("delete", None)
        ch = MORSE.get(code, "?")
        self.text += ch
        return ("letter", ch)


def encode(text):
    """Text to Morse: spaces between letters, ' / ' between words (for the cheat sheet)."""
    reverse = {v: k for k, v in MORSE.items()}
    return " / ".join(" ".join(reverse[c] for c in word if c in reverse)
                      for word in text.upper().split())
