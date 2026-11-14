# Helen server: band taps -> Morse -> AI sentence -> spoken out loud.
#   .venv/bin/python -m helen.main 46
import argparse
import threading
import time

from helen.band import connect
from helen.expand import QUICK, expand
from helen.taps import TapReader
from helen.voice import speak

parser = argparse.ArgumentParser()
parser.add_argument("number", nargs="?", type=int, default=None)
parser.add_argument("--sim", action="store_true")
args = parser.parse_args()

history = []   # recent lines of the conversation, so the AI has context


def log(line):
    print(time.strftime("%H:%M:%S"), line, flush=True)


def changed(event, d):
    if event != "symbol":
        log(f"  [{event:<6}] text: {d.text()}")


def is_stray(words):
    """Only loose single letters that are not a quick phrase: accidental bumps, not a message."""
    return words not in QUICK and all(len(w) == 1 for w in words.split())


def sent(words):
    if is_stray(words):
        log(f"--- ignored stray taps: {words}")
        return
    log(f">>> TAPPED: {words}")
    threading.Thread(target=say, args=(words,), daemon=True).start()


def say(words):
    try:
        sentence = expand(words, "\n".join(history[-6:]))
        log(f"<<< SAYING: {sentence}")
        history.append("Me: " + sentence)
        speak(sentence)
    except Exception as e:   # keep the server alive whatever the AI or voice service does
        log(f"!!! could not speak: {e}")


band = connect(args.number, args.sim)
log(f"Connected to {band.name}")
band.on("disconnect", lambda e: log(f"!!! band disconnected: {getattr(e, 'reason', e)}"))
band.on("reconnecting", lambda e: log("!!! band connection lost, reconnecting (double-tap the band if it takes long)"))
band.on("reconnected", lambda e: log("!!! band reconnected"))
TapReader(band, sent, changed)
log("Ready: tap Morse, turn wrist over and hold 2s to speak. Ctrl+C to stop.")
try:
    band.wait(4 * 3600)
except KeyboardInterrupt:
    pass
band.disconnect()
