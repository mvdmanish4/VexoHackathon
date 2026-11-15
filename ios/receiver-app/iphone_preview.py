"""Vexo live haptic preview for Pyto on an iPhone. Keep Pyto in the foreground."""

import ctypes
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def ahap(steps, dot_ms):
    """Convert Vexo's alternating Morse pulse and gap units to Core Haptics events."""
    events = []
    offset = 0
    for step in steps:
        for index, units in enumerate(step["pattern"]):
            if index % 2 == 0:
                events.append({"Event": {
                    "EventType": "HapticContinuous",
                    "Time": offset * dot_ms / 1000,
                    "EventDuration": units * dot_ms / 1000,
                    "EventParameters": [
                        {"ParameterID": "HapticIntensity", "ParameterValue": 1},
                        {"ParameterID": "HapticSharpness", "ParameterValue": 0.65},
                    ],
                }})
            offset += units
        offset += step["gap"]
    return {"Version": 1.0, "Pattern": events}, offset * dot_ms / 1000


class HapticOutput:
    def __init__(self):
        from CoreHaptics import CHHapticEngine
        from Foundation import NSData

        if not CHHapticEngine.capabilitiesForHardware().supportsHaptics:
            raise RuntimeError("This device does not support Core Haptics.")
        self.data_class = NSData
        self.engine = CHHapticEngine.alloc().initAndReturnError_(None)
        if self.engine is None:
            raise RuntimeError("Could not create the iPhone haptic engine.")
        self.engine.setPlaysHapticsOnly_(True)
        if not self.engine.startAndReturnError_(None):
            raise RuntimeError("Could not start the iPhone haptic engine.")

    def play(self, steps, dot_ms):
        from rubicon.objc.runtime import autoreleasepool

        pattern, duration = ahap(steps, dot_ms)
        if not pattern["Pattern"]:
            return
        data = json.dumps(pattern).encode("utf-8")
        buffer = ctypes.create_string_buffer(data)
        with autoreleasepool():
            native = self.data_class.dataWithBytes_length_(ctypes.cast(buffer, ctypes.c_void_p), len(data))
            if not self.engine.playPatternFromData_error_(native, None):
                raise RuntimeError("The iPhone could not play this pattern. Keep Pyto in the foreground.")
        time.sleep(duration)

    def close(self):
        self.engine.stopWithCompletionHandler_(None)


def fetch(address, code, cursor, session):
    query = urlencode({"after": cursor, "session": session})
    request = Request(f"{address}/transcripts?{query}", headers={"X-Vexo-Code": code})
    with urlopen(request, timeout=4) as response:
        return json.load(response)


def receive(address, code, dot_ms, output):
    cursor = 0
    session = ""
    retrying = False
    while True:
        try:
            feed = fetch(address, code, cursor, session)
        except HTTPError as error:
            if error.code == 401:
                raise ValueError("The receiver code was rejected. Run the script again with the code from your Mac.") from None
            raise RuntimeError(f"The Mac receiver returned HTTP {error.code}.") from None
        except (URLError, TimeoutError):
            if not retrying:
                print("Waiting for the Mac. Check Wi-Fi and Local Network access.", flush=True)
            retrying = True
            time.sleep(1)
            continue
        if retrying or session != feed["session"]:
            print("Connected to the Vexo feed.", flush=True)
        retrying = False
        session = feed["session"]
        if feed["missed"]:
            print("Some older turns are no longer available.", flush=True)
        for turn in feed["messages"]:
            cursor = turn["id"]
            if turn.get("kind") == "reply":
                continue
            message = turn["selected"]
            print(f"Playing turn {turn['id']}: {message['text']}", flush=True)
            # Play one letter at a time, as in the standalone Vexo receiver.
            for step in message["steps"]:
                output.play([step], dot_ms)
            time.sleep(7 * dot_ms / 1000)
        if not feed["messages"]:
            time.sleep(0.45)


def main():
    address = input("Mac receiver address [http://MacBook-Pro.local:8765]: ").strip().rstrip("/")
    address = address or "http://MacBook-Pro.local:8765"
    url = urlsplit(address)
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or
            url.password or url.path or url.query or url.fragment):
        raise ValueError("Enter the Mac receiver address, including http:// and its port.")
    code = input("Vexo receiver code from the Mac: ").strip()
    dot_ms = int(input("Milliseconds per dot [120]: ").strip() or 120)
    if not 60 <= dot_ms <= 300:
        raise ValueError("Use a dot length between 60 and 300 milliseconds.")

    from rubicon.objc.runtime import autoreleasepool

    with autoreleasepool():
        output = HapticOutput()
        try:
            print("Test: three short pulses for S.", flush=True)
            output.play([{"pattern": [1, 1, 1, 1, 1], "gap": 7}], dot_ms)
            receive(address, code, dot_ms, output)
        finally:
            output.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Vexo preview stopped.")
    except (ImportError, RuntimeError, ValueError) as error:
        print(f"Vexo: {error}")
