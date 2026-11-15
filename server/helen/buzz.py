"""Vibration patterns for the phone page: a list of [on_ms, off_ms] pulses.

The server builds the pattern (so it knows exactly how long the phone will buzz) and the
page just plays it. On iPhone each "on" is a burst of rapid haptic ticks; on Android it is
one vibration of that length.
"""
from helen.morse import encode

DOT, DASH = 120, 360            # buzz lengths (ms)
GAP, LETTER, WORD = 160, 420, 800   # pauses after a symbol / letter / word (ms)


def pattern(words, seconds):
    """Morse of `words` as pulses, repeated or cut so it lasts about `seconds`."""
    pulses = []
    for word in encode(words).split(" / "):
        for letter in word.split():
            for s in letter:
                pulses.append([DOT if s == "." else DASH, GAP])
            pulses[-1][1] = LETTER
        if pulses:
            pulses[-1][1] = WORD
    if not pulses:
        pulses = [[DASH, WORD]]
    out, total, target = [], 0, seconds * 1000
    while total < target:                     # loop the message until the time is filled
        for on, off in pulses:
            if total + on > target:
                break
            out.append([on, off])
            total += on + off
        else:
            continue
        break
    return out


def length(pulses):
    return sum(on + off for on, off in pulses) / 1000
