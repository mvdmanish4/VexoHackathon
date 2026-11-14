"""Turns band gestures into Morse: tap = dot, double-tap = dash, wrist turned and held = send.

Pauses adapt to the person's tapping speed, and 6+ dots in one letter deletes the last letter
(both in helen.morse.TapDecoder).
"""
import threading
import time

from helen.morse import TapDecoder

TAP_THRESHOLD = 0.45   # g; lower = more sensitive (0.8 missed real taps, 0.35 caught arm movement)
TURN_QUIET = 2.5       # seconds to ignore taps after a send (turning back makes fake taps)
TURN_TAIL = 2.0        # a tap this soon before a send came from turning the wrist: drop it
STALE = 10.0           # taps not sent within this many seconds are cleared, so they can't
                       # merge into the next answer
LETTER_GAP = 3.0       # pause that ends a letter: forgiving for slow, careful tapping
WORD_GAP = 6.0         # pause that ends a word
ADAPTIVE = False       # adapting shortened the pauses too much for careful tappers
PAIR_WINDOW = 0.8      # two single taps this close together = a dash: the band often reports a
                       # quick double-tap as two single taps instead of one "double-tap"
# Send = wrist turned palm-up AND held for 2 s (the band reports the hold as a "tilt").
# A tilt alone is not enough (the wrist moves while tapping), and a quick turn to palm-up
# alone is not enough either.
SEND_FACES = ("+z", "+x", "-x")   # palm up (+z), or a quarter turn either way (+x, -x);
                            # measured on band 46, where the resting position is -z
TURNED_Z = -0.5        # g: resting is about -1 g along z. Above this the wrist is turned more than
                       # ~70 degrees (read from the motion sensor, since the band only reports
                       # "orientation" for a clean, straight turn)
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
        self.last_pair = 0.0         # time we made a dash from two single taps
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
            self.last_pair = now
            self._symbol(self.decoder.dash, "two quick taps = -")

    def _double(self):
        if time.monotonic() - self.last_pair < 0.8:
            return                   # the band also reported the pair we already made a dash from
        with self.lock:
            # A single tap still waiting (under PAIR_WINDOW old) is the first tap of this same
            # double-tap: the band sometimes reports both. Count the pair once.
            self.pending = None
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
        return self.face in SEND_FACES or self.az > TURNED_Z

    def _tilt(self):
        if self.palm_up():
            self._send()
        else:
            self.tell("band", f"wrist moved (face {self.face}, z {self.az:+.2f} g), not palm-up: no send")

    def _send(self):
        now = time.monotonic()
        self.last_turn = now
        with self.lock:
            self.pending = None          # a waiting tap at this moment is the turn itself
        dec = self.decoder
        with dec._lock:
            # Only when something else was tapped first: a lone tap is the message itself.
            if (dec.current and dec._last is not None and now - dec._last < TURN_TAIL
                    and (len(dec.current) > 1 or dec.text.strip())):
                dec.current = dec.current[:-1]
                self.tell("band", "dropped the last tap: it came from turning the wrist")
        dec.request_send()

    def _clear_stale(self):
        dec = self.decoder
        with dec._lock:
            stale = (dec._last is not None and (dec.text.strip() or dec.current)
                     and time.monotonic() - dec._last > STALE)
            if stale:
                dropped = (dec.text + dec.current).strip()
                dec.text, dec.current, dec._last = "", "", None
        if stale:
            self.tell("band", f"cleared unsent taps ({dropped}): nothing was sent for {STALE:.0f} s")

    def _clock(self):
        while True:
            self._flush()
            self._clear_stale()
            self.decoder.tick(time.monotonic())
            time.sleep(0.05)
