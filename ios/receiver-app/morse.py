"""Translate English transcripts to International Morse playback units."""

import unicodedata

MORSE = dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    (".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- "
     ".--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. "
     "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.").split(),
    strict=True,
))
MORSE.update({
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", ":": "---...",
    "-": "-....-", '"': ".-..-.", "=": "-...-", "+": ".-.-.",
    "@": ".--.-.", "!": "-.-.--",
})
TYPOGRAPHY = str.maketrans({
    "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
})


def encode(text: str) -> dict:
    # Keep the original transcript for review. Render unknown symbols as '?'
    # and report them alongside the pattern instead of dropping them silently.
    normalized = unicodedata.normalize("NFKD", text.translate(TYPOGRAPHY)).upper()
    words = []
    unsupported = set()
    for word in normalized.split():
        letters = []
        for char in word:
            if unicodedata.combining(char):
                continue
            if char not in MORSE:
                unsupported.add(char)
            letters.append(MORSE.get(char, MORSE["?"]))
        if letters:
            words.append(letters)

    steps = []
    for word_index, word in enumerate(words):
        for letter_index, code in enumerate(word):
            pattern = []
            for index, symbol in enumerate(code):
                if index:
                    pattern.append(1)
                pattern.append(1 if symbol == "." else 3)
            gap = 3 if letter_index + 1 < len(word) else 7
            if word_index + 1 == len(words) and letter_index + 1 == len(word):
                gap = 0
            steps.append({"pattern": pattern, "gap": gap})
    return {
        "type": "transcript",
        "text": text,
        "morse": " / ".join(" ".join(word) for word in words),
        "steps": steps,
        "unsupported": sorted(unsupported),
    }
