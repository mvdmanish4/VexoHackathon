"""Connecting to the Vexo band (real or pretend)."""
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / "vexo-open-kit" / "python"
sys.path.insert(0, str(KIT))

from vexo_open.sync import Band  # noqa: E402


def connect(number=None, sim=False):
    """Connect to band `number` over Bluetooth, or to the pretend band if sim."""
    if sim:
        return Band.connect(number or 42, transport="sim")
    if number is None:
        sys.exit("Give your band number (it is on the bag), e.g. 42")
    print("Double-tap the band now (light blinks blue), connecting...", flush=True)
    return Band.connect(number)
