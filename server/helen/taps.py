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
# Send = wrist turned palm-up AND held for 2 s (the band reports the hold as a "tilt").
# A tilt alone is not enough (the wrist moves while tapping), and a quick turn to palm-up
# alone is not enough either.
SEND_FACE = "+z"       # face pointing up when the palm is up (measured on band 46; rest is -z)
PALM_UP_Z = 0.4        # g: gravity along +z above this = palm up (read from the motion sensor,
                       # since the band only reports "orientation" for a clean, straight turn)
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
        self.face = None
        self.az = 0.0                # latest gravity along z, in g
        band.on("orientation", lambda e: setattr(self, "face", e.face))
        band.on("motion", lambda e: setattr(self, "az", e.az))
        band.on("tilt", lambda e: self._tilt())
        band.set_events(kinds=["tap", "double-tap", "tilt", "orientation"], tap_threshold=TAP_THRESHOLD)
        band.configure(events=True, motion=10, sensors="accel")
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
            dot_first = self.pending is not None   # a single tap just before is its own dot
            self.pending = None
        if dot_first:
            self._symbol(self.decoder.dot, "tap = .")
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

    def palm_up(self):
        return self.face == SEND_FACE or self.az > PALM_UP_Z

    def _tilt(self):
        if self.palm_up():
            self._send()
        else:
            self.tell("band", f"wrist moved (face {self.face}, z {self.az:+.2f} g), not palm-up: no send")

    def _send(self):
        self.last_turn = time.monotonic()
        self.decoder.request_send()

    def _clock(self):
        while True:
            self._flush()
            self.decoder.tick(time.monotonic())
            time.sleep(0.05)
