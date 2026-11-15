"""Listens to the band's microphone and turns finished sentences into text (Deepgram).

Uses the Vexo kit's speech.py. Everything the band's mic hears goes to Deepgram while on.
"""
import os
import sys
import threading
import time
from pathlib import Path

from helen.band import KIT

sys.path.insert(0, str(KIT.parent / "examples" / "python"))
import speech  # noqa: E402  (the kit's Deepgram client)
from ogg_opus import OggOpusWriter  # noqa: E402

STALL = 60.0      # seconds with sound flowing but no words from Deepgram: reconnect to it
RECORDING = Path(__file__).resolve().parent.parent / "logs" / "mic.ogg"   # last 60 s, for debugging


class Listener:
    """Calls on_heard(sentence) for each finished sentence, except while muted
    (our own voice is playing, so the mic would hear us)."""

    def __init__(self, band, on_heard, log=print):
        self.on_heard = on_heard
        self.log = log
        self.muted_until = 0.0
        self.packets = 0                             # sound packets from the band (50 a second)
        self.partial = ""
        self.last_words = time.monotonic()           # when Deepgram last returned any words
        self._open_ears()
        band.on("audio", self._audio)
        band.on("mic-level", lambda e: setattr(self, "level", e.rms_db))
        self.level = None
        band.configure(audio=True, mic_level=2)      # band light goes solid blue: mic on
        threading.Thread(target=self._health, daemon=True).start()

    def _open_ears(self):
        """Connect to Deepgram. A noisy room is never silent, so a silence-based sentence
        end never comes: utterance_end_ms ends a sentence after a 1 s gap between words."""
        ears = speech.create(endpointing=500, utterance_end_ms=1000)
        kit_message = ears._message

        def message(m):
            kit_message(m)
            if m.get("type") == "UtteranceEnd":
                ears._sentence_ends()
        ears._message = message
        ears.start(self._text)
        self.ears = ears
        self.last_words = time.monotonic()

    def _reopen_ears(self):
        """Deepgram went quiet although sound is flowing: the connection stalled. Reconnect."""
        old = self.ears
        self._open_ears()
        try:
            old.stop(wait=1.0)
        except Exception:
            pass

    def _audio(self, a):
        self.packets += 1
        self.ears.feed(a.opus, a.seq)
        if self.packets == 1 and not getattr(self, "ogg", None):
            self.ogg = OggOpusWriter(str(RECORDING))
        if getattr(self, "ogg", None):
            self.ogg.write(a.seq, a.opus)
            if self.ogg.frames >= 3000:          # 60 s: close it so it can be played
                self.ogg.close()
                self.ogg = False

    def _health(self):
        """Every 10 s: is sound arriving, how loud, and is Deepgram answering.
        No sound for 30 s means the band is gone: exit, and run.sh starts a fresh connection."""
        silent = 0
        while True:
            time.sleep(10)
            self.log(f"mic: {self.packets} packets in 10s, loudness {self.level} dB below max, "
                     f"deepgram error: {getattr(self.ears, 'error', None)}, last partial: {self.partial!r}")
            silent = silent + 1 if self.packets == 0 else 0
            self.packets_seen = self.packets > 0
            self.packets = 0
            if self.packets_seen and time.monotonic() - self.last_words > STALL:
                self.log(f"!!! Deepgram returned no words for {STALL:.0f} s: reconnecting to Deepgram")
                self._reopen_ears()
            if silent >= 3:
                self.log("!!! no sound from the band for 30 s: restarting to reconnect (double-tap the band)")
                os._exit(3)

    def mute(self, seconds):
        self.muted_until = max(self.muted_until, time.monotonic() + seconds)

    def _text(self, text, final):
        if text:
            self.last_words = time.monotonic()
        if not final:
            self.partial = text
        if final and text and time.monotonic() >= self.muted_until:
            self.on_heard(text)
