# Live test: tap Morse on the band and watch letters appear. Turn the wrist over to send.
#   .venv/bin/python -m tools.tap_to_text 46
import argparse

from helen.band import connect
from helen.taps import TapReader

parser = argparse.ArgumentParser()
parser.add_argument("number", nargs="?", type=int, default=None)
parser.add_argument("--sim", action="store_true")
parser.add_argument("--seconds", type=float, default=600)
args = parser.parse_args()

band = connect(args.number, args.sim)
print("Connected to", band.name, flush=True)


def changed(event, d):
    print(f"  [{event:<6}] {d.symbols or ' ':<6} text: {d.text()}", flush=True)


def sent(message):
    print(f"\n>>> SENT: {message}\n", flush=True)


TapReader(band, sent, changed)
print("tap = dot, double-tap = dash, pause 2s = next letter, 4.5s = next word,", flush=True)
print("turn wrist over = send. Ctrl+C to stop.", flush=True)
try:
    band.wait(args.seconds)
except KeyboardInterrupt:
    pass
band.disconnect()
