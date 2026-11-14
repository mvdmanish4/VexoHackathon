"""Listens to the band's microphone and turns finished sentences into text (Deepgram).

Uses the Vexo kit's speech.py. Everything the band's mic hears goes to Deepgram while on.
"""
import sys
import time

from helen.band import KIT

sys.path.insert(0, str(KIT.parent / "examples" / "python"))
import speech  # noqa: E402  (the kit's Deepgram client)


class Listener:
    """Calls on_heard(sentence) for each finished sentence, except while muted
    (our own voice is playing, so the mic would hear us)."""

    def __init__(self, band, on_heard):
        self.on_heard = on_heard
        self.muted_until = 0.0
        self.ears = speech.create(endpointing=500)   # 0.5 s pause ends a sentence
        self.ears.start(self._text)
        band.on("audio", lambda a: self.ears.feed(a.opus, a.seq))
        band.configure(audio=True)                   # band light goes solid blue: mic on

    def mute(self, seconds):
        self.muted_until = max(self.muted_until, time.monotonic() + seconds)

    def _text(self, text, final):
        if final and text and time.monotonic() >= self.muted_until:
            self.on_heard(text)
