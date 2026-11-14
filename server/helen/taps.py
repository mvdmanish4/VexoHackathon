"""Turns band gestures into Morse: tap = dot, double-tap = dash, wrist turned and held = send.

Pauses adapt to the person's tapping speed, and 6+ dots in one letter deletes the last letter
(both in helen.morse.TapDecoder).
"""
import threading
import time

from helen.morse import TapDecoder

TAP_THRESHOLD = 0.5    # g; lower = more sensitive (band default 0.8 missed taps)
TURN_QUIET = 0.6       # seconds to ignore taps after a send (turning makes fake taps)
LETTER_GAP = 2.0       # starting pauses, measured on the real band; they adapt from here
WORD_GAP = 4.5
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
            letter_gap=LETTER_GAP, word_gap=WORD_GAP, send_gap=0,
            on_letter=lambda ch: tell("letter", self.decoder.text),
            on_word=lambda text: tell("word", text),
            on_delete=lambda: tell("delete", self.decoder.text),
            on_message=on_send)
        band.on("tap", lambda e: self._symbol(self.decoder.dot))
        band.on("double-tap", lambda e: self._symbol(self.decoder.dash))
        band.on("tilt", lambda e: self._send())
        band.set_events(kinds=["tap", "double-tap", "tilt"], tap_threshold=TAP_THRESHOLD)
        band.configure(events=True)
        threading.Thread(target=self._clock, daemon=True).start()

    def _symbol(self, add):
        now = time.monotonic()
        if now - self.last_turn >= TURN_QUIET:
            add(now)

    def _send(self):
        self.last_turn = time.monotonic()
        self.decoder.request_send()

    def _clock(self):
        while True:
            self.decoder.tick(time.monotonic())
            time.sleep(0.05)
