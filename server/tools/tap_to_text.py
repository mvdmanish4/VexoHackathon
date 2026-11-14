# Live test: tap Morse on the band and watch letters appear. Turn the wrist over to send.
#   .venv/bin/python -m tools.tap_to_text 46
import argparse
import time

from helen.band import connect
from helen.taps import TapReader

parser = argparse.ArgumentParser()
parser.add_argument("number", nargs="?", type=int, default=None)
parser.add_argument("--sim", action="store_true")
parser.add_argument("--seconds", type=float, default=600)
args = parser.parse_args()

band = connect(args.number, args.sim)
print("Connected to", band.name, flush=True)


def log(line):
    print(time.strftime("%H:%M:%S"), line, flush=True)


def changed(event, text):
    log(f"  [{event:<6}] text: {text}")


def sent(message):
    log(f">>> SENT: {message}")


def raw(e):
    face = getattr(e, "face", None)
    log(f"band: {e.kind}" + (f" face={face}" if face else ""))


band.on("event", raw)
band.on("disconnect", lambda e: log(f"!!! band disconnected: {getattr(e, 'reason', e)}"))
band.on("reconnected", lambda e: log("!!! band reconnected"))


TapReader(band, sent, changed)
print("tap = dot, double-tap = dash, pause 2s = next letter, 4.5s = next word,", flush=True)
print("turn wrist over = send. Ctrl+C to stop.", flush=True)
try:
    band.wait(args.seconds)
except KeyboardInterrupt:
    pass
band.disconnect()
