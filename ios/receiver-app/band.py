"""Send Vexo SDK speech callbacks to the receiver, including typed simulation."""

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from band_reply import BandReply

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
BAND_NUMBER = 46
DEMO = (
    "Um, could you please tell me if you're ready to go yet?",
    "Just to be clear, don't go to Gate 4. Wait for me at Gate 2 at 5:30 PM. That's Gate 2 at 5:30 PM.",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sim", action="store_true", help="Simulate finalized transcripts using the SDK speech interface")
    source.add_argument("--live", action="store_true", help="Connect to your team's configured Vexo band")
    parser.add_argument("--say", action="append", help="Simulated transcript, repeat for multiple turns")
    source.add_argument("--tap-only", action="store_true", help="Test physical band replies without Deepgram")
    parser.add_argument("--usb", action="store_true", help="Connect to your numbered band over USB")
    parser.add_argument("--band", type=int, default=BAND_NUMBER, help="Number printed on your team's band bag (default: %(default)s)")
    parser.add_argument("--verbatim", action="store_true", help="Play the full transcript without calling OpenAI")
    parser.add_argument("--json", action="store_true", help="Print the receiver response for each turn as JSON")
    args = parser.parse_args()
    if (args.say and not args.sim) or (args.usb and args.sim):
        parser.error("--say is for simulation. --usb is for a numbered band.")
    kit = ROOT / "vexo-open-kit" / "examples" / "python"
    if not (kit / "speech.py").is_file():
        parser.error("Install Vexo Open Kit using the command in README.md.")
    sys.path.insert(0, str(kit))
    import speech

    pending = queue.Queue()

    def on_text(text, final):
        if final and text.strip():
            pending.put(("transcripts", text))

    def deliver():
        with httpx.Client(base_url="http://127.0.0.1:8765", timeout=10) as client:
            while (item := pending.get()) is not None:
                path, transcript = item
                try:
                    response = client.post(f"/{path}", json={"text": transcript, "compact": not args.verbatim})
                    response.raise_for_status()
                    r = response.json()
                    if args.json:
                        print(json.dumps(r), flush=True)
                        continue
                    if path == "replies":
                        print(f"Band reply delivered: {transcript}", flush=True)
                        continue
                    print(
                        f"Turn {r['id']}: {r['status']}, {r['original_units']} → {r['selected_units']} Morse units"
                        + (f", OpenAI {r['openai_ms']} ms" if r["openai_ms"] is not None else ""),
                        flush=True,
                    )
                except httpx.HTTPStatusError as error:
                    errors.append(f"Receiver returned HTTP {error.response.status_code}.")
                    print(errors[-1], file=sys.stderr, flush=True)
                except httpx.RequestError:
                    errors.append("Couldn't reach the receiver. Check that the Mac server is running.")
                    print(errors[-1], file=sys.stderr, flush=True)

    errors = []
    delivery = threading.Thread(target=deliver, name="vexo-transcripts")
    delivery.start()
    try:
        if args.sim:
            class SimulatedSpeech(speech.Speech):
                def say(self, text):
                    self._say(text, True)

            ears = speech.create(SimulatedSpeech).start(on_text)
            for text in args.say or DEMO:
                ears.say(text)
        else:
            from vexo_open.sync import Band

            if not args.tap_only:
                speech.find_key()
            print(f"Connecting to band {args.band} over {'USB' if args.usb else 'Bluetooth'}…", flush=True)
            band = Band.connect(args.band, "serial" if args.usb else "ble")
            try:
                if band.number != args.band:
                    parser.error("The connected band number does not match your team's band.")
                print(f"Connected to band {band.number}. Single tap = dot, double tap = dash.", flush=True)
                print("Pause 1.5 seconds between letters and 5 seconds to send a reply.", flush=True)
                ears = None
                mute_until = 0.0
                tap_events = queue.Queue()

                def publish_reply(text):
                    nonlocal mute_until
                    mute_until = time.monotonic() + min(20, max(5, len(text) / 8 + 4))
                    pending.put(("replies", text))

                reply = BandReply(publish_reply)

                def feed_audio(event):
                    if time.monotonic() >= mute_until:
                        ears.feed(event)

                def on_tap(event):
                    nonlocal mute_until
                    now = time.monotonic()
                    mute_until = max(mute_until, now + 5.5)
                    tap_events.put((event.kind, now))

                band.set_events(kinds=["tap", "double-tap"])
                band.on("tap", on_tap)
                band.on("double-tap", on_tap)
                if not args.tap_only:
                    print("Tell everyone nearby before enabling the microphone. Final transcripts can also be sent to OpenAI.")
                    input("Press Enter to start listening. Press Ctrl+C to stop. ")
                    ears = speech.create(endpointing=550).start(on_text)
                    band.on("audio", feed_audio)
                try:
                    band.configure(events=True, **({"audio": True} if ears else {}))
                    while band.connected and (not ears or not ears.error):
                        try:
                            kind, timestamp = tap_events.get(timeout=0.1)
                        except queue.Empty:
                            reply.advance(time.monotonic())
                        else:
                            print(f"Band gesture: {kind}", flush=True)
                            reply.tap(kind, timestamp)
                finally:
                    try:
                        if band.connected:
                            band.configure(events=False, **({"audio": False} if ears else {}))
                    finally:
                        if ears:
                            ears.stop()
                if (ears and ears.error) or not band.connected:
                    errors.append("Band session stopped. Reconnect to resume.")
                    print(errors[-1], file=sys.stderr)
            finally:
                band.disconnect()
    except KeyboardInterrupt:
        pass
    finally:
        pending.put(None)
        delivery.join()
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
