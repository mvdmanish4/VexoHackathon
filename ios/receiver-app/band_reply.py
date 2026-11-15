"""Decode timed Vexo tap events into a reply without involving the audio service."""

from morse import MORSE

LETTERS = {code: char for char, code in MORSE.items() if char.isalnum()}
DOUBLE_WINDOW = 0.48
LETTER_PAUSE = 1.5
WORD_PAUSE = 2.8
SEND_PAUSE = 5.0


class BandReply:
    def __init__(self, publish, on_error=print):
        self.publish = publish
        self.on_error = on_error
        self.last = None
        self.pending_dot = None
        self.symbols = ""
        self.text = ""

    def tap(self, kind, now):
        self.advance(now)
        if self.last is not None:
            pause = now - self.last
            if pause >= LETTER_PAUSE:
                self._finish_letter()
                if pause >= WORD_PAUSE and self.text:
                    self.text += " "

        if kind == "tap":
            if self.pending_dot is not None:
                self.symbols += "."
            self.pending_dot = now
        else:
            self.pending_dot = None
            self.symbols += "-"
        self.last = now

    def advance(self, now):
        if self.pending_dot is not None and now - self.pending_dot > DOUBLE_WINDOW:
            self.symbols += "."
            self.pending_dot = None
        if self.last is None or now - self.last < SEND_PAUSE:
            return
        self._finish_letter()
        reply = self.text.strip()
        self.last = None
        self.text = ""
        if reply:
            self.publish(reply)

    def _finish_letter(self):
        if not self.symbols:
            return
        letter = LETTERS.get(self.symbols)
        if letter is None:
            self.on_error(f"Unknown band Morse letter {self.symbols}. Restart the reply.")
            self.text = ""
        else:
            self.text += letter
        self.symbols = ""
