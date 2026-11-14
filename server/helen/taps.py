"""Turns band gestures into Morse: tap = dot, double-tap = dash, wrist turned and held = send."""
import threading
import time

from helen.morse import Decoder

TAP_THRESHOLD = 0.5    # g; lower = more sensitive (band default 0.8 missed taps)
TURN_QUIET = 0.6       # seconds to ignore taps after a send (turning makes fake taps)
# Send = wrist turned and held for 2 s (the band reports it as a "tilt"). A quick
# orientation change is not used: the wrist moves that much while tapping.


class TapReader:
    """Listens to the band and calls on_send(message) when the user sends."""

    def __init__(self, band, on_send, on_change=None):
        self.band = band
        self.on_send = on_send
        self.decoder = Decoder(on_change=on_change)
        self.last_turn = 0.0
        band.on("tap", lambda e: self._symbol("."))
        band.on("double-tap", lambda e: self._symbol("-"))
        band.on("tilt", lambda e: self._send())
        band.set_events(kinds=["tap", "double-tap", "tilt"],
                        tap_threshold=TAP_THRESHOLD)
        band.configure(events=True)
        threading.Thread(target=self._clock, daemon=True).start()

    def _symbol(self, s):
        now = time.monotonic()
        if now - self.last_turn < TURN_QUIET:
            return
        self.decoder.add(s, now)

    def _mark_turn(self):
        self.last_turn = time.monotonic()

    def _send(self):
        self._mark_turn()
        message = self.decoder.take()
        if message:
            self.on_send(message)

    def _clock(self):
        while True:
            self.decoder.tick(time.monotonic())
            time.sleep(0.1)
