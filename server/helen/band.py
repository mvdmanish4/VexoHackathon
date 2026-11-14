"""Connecting to the Vexo band (real or pretend)."""
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / "vexo-open-kit" / "python"
sys.path.insert(0, str(KIT))

from vexo_open.sync import Band, VexoError  # noqa: E402


def connect(number=None, sim=False):
    """Connect to band `number` over Bluetooth (retrying until found), or the pretend band."""
    if sim:
        return Band.connect(number or 42, transport="sim")
    if number is None:
        sys.exit("Give your band number (it is on the bag), e.g. 42")
    while True:
        print("Looking for the band... double-tap it (light blinks blue).", flush=True)
        try:
            return Band.connect(number)
        except VexoError as e:
            if e.code != "not-found-nearby":
                raise
            print("Not found yet, trying again.", flush=True)
