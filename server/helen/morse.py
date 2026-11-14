"""Morse code: turning dots and dashes into letters, and letters into dots and dashes."""

CODE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....",
    "6": "-....", "7": "--...", "8": "---..", "9": "----.", "0": "-----",
}
LETTER = {v: k for k, v in CODE.items()}


def encode(text):
    """'HI' -> '.... ..' (letters split by spaces, words by ' / ')."""
    words = text.upper().split()
    return " / ".join(" ".join(CODE[c] for c in w if c in CODE) for w in words)


class Decoder:
    """Collects dots and dashes, and uses pauses to finish letters and words.

    Call add('.') or add('-') for each tap, and tick(now) often (a few times a second)
    so that pauses are noticed. Times are in seconds (time.monotonic()).
    """

    def __init__(self, letter_gap=2.0, word_gap=4.5, on_change=None):
        self.letter_gap = letter_gap  # pause that ends a letter
        self.word_gap = word_gap      # pause that ends a word
        self.on_change = on_change    # called with (event, decoder) after every change
        self.clear()

    def clear(self):
        self.symbols = ""   # dots and dashes of the letter being tapped
        self.words = []     # finished words
        self.word = ""      # letters of the word being tapped
        self.last = None    # time of the last tap

    def add(self, symbol, now):
        self.symbols += symbol
        self.last = now
        self._tell("symbol")

    def tick(self, now):
        if self.last is None:
            return
        quiet = now - self.last
        if self.symbols and quiet >= self.letter_gap:
            self.word += LETTER.get(self.symbols, "?")
            self.symbols = ""
            self._tell("letter")
        if self.word and quiet >= self.word_gap:
            self.words.append(self.word)
            self.word = ""
            self._tell("word")

    def text(self):
        """Everything finished so far, plus the letter/word still in progress."""
        word = self.word + (LETTER.get(self.symbols, "?") if self.symbols else "")
        return " ".join(self.words + ([word] if word else []))

    def take(self):
        """Return the whole message and start fresh (used when the user sends)."""
        message = self.text().replace("?", "").strip()
        self.clear()
        return message

    def _tell(self, event):
        if self.on_change:
            self.on_change(event, self)
