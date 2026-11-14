# Prints every gesture the band feels, with the time since the previous one.
# Used to learn how the real band reports taps vs double-taps.
#   .venv/bin/python -m tools.tap_probe 42        (your band number)
#   .venv/bin/python -m tools.tap_probe --sim     (pretend band)
import argparse
import time

from helen.band import connect

parser = argparse.ArgumentParser()
parser.add_argument("number", nargs="?", type=int, default=None)
parser.add_argument("--sim", action="store_true")
parser.add_argument("--seconds", type=float, default=600)
args = parser.parse_args()

band = connect(args.number, args.sim)
print("Connected to", band.name, flush=True)
last = [time.monotonic()]


def show(e):
    now = time.monotonic()
    face = getattr(e, "face", None)
    extra = f" face={face}" if face else ""
    print(f"{e.kind:<12}{extra:<10} +{now - last[0]:.2f}s", flush=True)
    last[0] = now


band.on("event", show)
band.configure(events=True)
print("Tap, double-tap, and turn your wrist. Ctrl+C to stop.", flush=True)
try:
    band.wait(args.seconds)
except KeyboardInterrupt:
    pass
band.disconnect()
