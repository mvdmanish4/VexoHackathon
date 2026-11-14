"""AI step for the other direction: a spoken sentence -> a few key words to feel as Morse."""
import re

from helen.expand import ask

PROMPT = """A deafblind person feels messages as Morse code vibrations, which is slow: every \
letter costs seconds. Shorten what was said to them to the fewest key words that keep the \
meaning, at most 4 words, in capital letters, using only A-Z, 0-9 and spaces. Keep names, \
numbers, and whether it is a question (end with the word Q if it is).

Examples:
Hi, would you like to grab a coffee with me later today? -> COFFEE LATER Q
My name is Priya, nice to meet you! -> PRIYA HI
The train to Boston leaves at 3:15 from platform 2. -> BOSTON 315 PLATFORM 2
Can you hear me okay? -> HEAR ME Q

Said: {sentence}"""


def compress(sentence):
    words = ask(PROMPT.format(sentence=sentence))
    if not words:   # no AI: keep the longest words
        words = " ".join(sorted(sentence.split(), key=len, reverse=True)[:4])
    return re.sub(r"[^A-Z0-9 ]", "", words.upper()).strip()
