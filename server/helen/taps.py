"""Turns band gestures into Morse: tap = dot, double-tap = dash, wrist turned and held = send.

Pauses adapt to the person's tapping speed, and 6+ dots in one letter deletes the last letter
(both in helen.morse.TapDecoder).
"""
import threading
import time

from helen.morse import TapDecoder

TAP_THRESHOLD = 0.5    # g; lower = more sensitive (band default 0.8 missed taps)
TURN_QUIET = 0.6       # seconds to ignore taps after a send (turning makes fake taps)
LETTER_GAP = 3.0       # pause that ends a letter: forgiving for slow, careful tapping
WORD_GAP = 6.0         # pause that ends a word
ADAPTIVE = False       # adapting shortened the pauses too much for careful tappers
PAIR_WINDOW = 0.5      # two single taps this close together = a dash: the band often reports a
                       # quick double-tap as two single taps instead of one "double-tap"
# Send = wrist turned and held for 2 s (the band reports it as a "tilt"). A quick
# orientation change is not used: the wrist moves that much while tapping.
# No automatic send after silence: stray taps would get spoken.


class TapReader:
    """Listens to the band and calls on_send(message) when the user sends.

    on_change(event, text) is called with "letter", "word" or "delete" and the text so far.
    """

    def __init__(self, band, on_send, on_change=None):
        self.band = band
        self.last_turn = 0.0
        tell = on_change or (lambda event, text: None)
        self.decoder = TapDecoder(
            letter_gap=LETTER_GAP, word_gap=WORD_GAP, send_gap=0, adaptive=ADAPTIVE,
            on_letter=lambda ch: tell("letter", self.decoder.text),
            on_word=lambda text: tell("word", text),
            on_delete=lambda: tell("delete", self.decoder.text),
            on_message=on_send)
        self.tell = tell
        self.pending = None          # time of a single tap that may still become a dash
        self.lock = threading.Lock()
        band.on("tap", lambda e: self._tap())
        band.on("double-tap", lambda e: self._double())
        band.on("tilt", lambda e: self._send())
        band.set_events(kinds=["tap", "double-tap", "tilt"], tap_threshold=TAP_THRESHOLD)
        band.configure(events=True)
        threading.Thread(target=self._clock, daemon=True).start()

    def _tap(self):
        now = time.monotonic()
        with self.lock:
            if self.pending is not None and now - self.pending <= PAIR_WINDOW:
                self.pending = None
                pair = True
            else:
                self.pending = now
                pair = False
        if pair:
            self._symbol(self.decoder.dash, "two quick taps = -")

    def _double(self):
        with self.lock:
            self.pending = None      # the band's own double-tap: any waiting tap was part of it
        self._symbol(self.decoder.dash, "double-tap = -")

    def _flush(self):
        """A single tap with no partner within PAIR_WINDOW is a dot."""
        with self.lock:
            due = self.pending is not None and time.monotonic() - self.pending > PAIR_WINDOW
            if due:
                self.pending = None
        if due:
            self._symbol(self.decoder.dot, "tap = .")

    def _symbol(self, add, what):
        now = time.monotonic()
        if now - self.last_turn >= TURN_QUIET:
            add(now)
            self.tell("band", f"{what}   letter so far: {self.decoder.current}")

    def _send(self):
        self.last_turn = time.monotonic()
        self.decoder.request_send()

    def _clock(self):
        while True:
            self._flush()
            self.decoder.tick(time.monotonic())
            time.sleep(0.05)
