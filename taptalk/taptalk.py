"""TapTalk: a deaf-blind, non-speaking person taps Morse on the Vexo band; the laptop speaks it.

    single tap = dot         double tap = dash
    short pause = next letter    longer pause = space   (pauses adapt to your speed)
    6 or more dots = delete the last letter
    turn the wrist over (palm up) = send      or stay still a few seconds = send

Gemini turns short taps into a full sentence, ElevenLabs speaks it in a human voice
(both optional: see README). Run in this folder:

    python3 taptalk.py --band N            your band (N is the number on the band's bag)
    python3 taptalk.py --band N --sim      the pretend band taps "HELP ME" and sends it
    python3 taptalk.py --band N --debug    also print every raw event (for tuning)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vexo-open-kit" / "python"))
from vexo_open.sync import Band  # noqa: E402
from vexo_open.transports.sim import SimTransport  # noqa: E402

from morse import MORSE, TapDecoder  # noqa: E402
from sponsors import Gemini, Speculator, Voice  # noqa: E402

FACES = ["+x", "-x", "+y", "-y", "+z", "-z"]


def parse_args():
    p = argparse.ArgumentParser(description="Tap Morse on the Vexo band; the laptop speaks it.")
    p.add_argument("--band", type=int, required=True,
                   help="your team's band number, printed on the band's bag (7 = Vexo-HACK-07)")
    p.add_argument("--sim", action="store_true", help="use the pretend band and tap a demo message")
    p.add_argument("--demo", default="HELP ME", help="what the pretend band taps with --sim (letters, digits, spaces)")
    p.add_argument("--debug", action="store_true", help="print every raw event from the band")
    p.add_argument("--no-ai", action="store_true", help="speak the tapped letters as they are (no Gemini)")
    p.add_argument("--no-eleven", action="store_true", help="use the Mac's voice, not ElevenLabs")
    p.add_argument("--letter-gap", type=float, default=1.2, help="starting pause (s) that ends a letter")
    p.add_argument("--word-gap", type=float, default=2.6, help="starting pause (s) that ends a word")
    p.add_argument("--send-gap", type=float, default=6.0, help="starting pause (s) that sends (0 = off)")
    p.add_argument("--fixed", action="store_true", help="keep the pauses fixed (do not adapt to the tapper)")
    p.add_argument("--no-speculate", action="store_true", help="do not prepare the voice while tapping")
    p.add_argument("--dedup", type=float, default=0,
                   help="drop a dot this many seconds before a dash, e.g. 0.3, only if --debug shows the band sends a tap before each double-tap (default off)")
    p.add_argument("--tap-threshold", type=float, default=0.8, help="tap strength in g, 0.2..8 (lower = lighter taps)")
    p.add_argument("--send-face", default="-z", choices=FACES,
                   help="the face pointing up that means 'send' (palm up); find yours with --debug")
    a = p.parse_args()
    if a.sim and not all(c in MORSE.values() or c == " " for c in a.demo.upper()):
        p.error("--demo can only use letters A-Z, digits and spaces")
    if not 1 <= a.band <= 999:
        p.error("--band must be your band's number, 1 to 999")
    return a


def main():
    a = parse_args()
    voice = Voice(use_eleven=not a.no_eleven, debug=a.debug)
    gemini = None if a.no_ai else Gemini()
    if gemini:
        gemini.warm_up()

    def show(letters, sentence):
        print("\n\n  Tapped : %s" % letters)
        if sentence and sentence.upper() != letters.upper():
            print("  Means  : %s   (Gemini)" % sentence)
        print()

    spec = Speculator(gemini, voice, show=show)

    def on_letter(ch):
        voice.say(ch if ch != "?" else "unknown", quick=True)

    def on_delete():
        voice.say("deleted", quick=True)

    def on_word(text_so_far):
        if not a.no_speculate:
            spec.prepare(text_so_far)       # start Gemini + ElevenLabs while they keep tapping

    def on_message(letters):
        spec.finish(letters, time.time())   # returns at once; the voice thread speaks

    dec = TapDecoder(letter_gap=a.letter_gap, word_gap=a.word_gap, send_gap=a.send_gap,
                     dedup=a.dedup, adaptive=not a.fixed, on_letter=on_letter,
                     on_delete=on_delete, on_word=on_word, on_message=on_message)

    transport = SimTransport(a.band, auto_tap=False) if a.sim else None
    print("Connecting to Vexo-HACK-%02d ... (double-tap the band first if it is not blinking blue)" % a.band)
    band = Band.connect(a.band, transport=transport) if a.sim else Band.connect(a.band, auto_reconnect=True)

    state = {"face": None}

    def on_event(e):
        if a.debug:
            print("\n  [event] %-12s arg=%s face=%s t=%s" % (e.kind, e.arg, e.get("face"), e.t))
        if e.kind == "tap":
            dec.dot(e.time)
        elif e.kind == "double-tap":
            dec.dash(e.time)
        elif e.kind == "orientation":
            face = e.get("face")
            if face == a.send_face and state["face"] not in (None, a.send_face):
                dec.request_send()
            state["face"] = face

    band.on("event", on_event)
    band.set_events(kinds=["tap", "double-tap", "orientation"], tap_threshold=a.tap_threshold)
    band.configure(events=True)

    print("Connected to %s." % band.name)
    print("Voice: %s.  Sentence help: %s." % (
        voice.engine,
        "off" if gemini is None else ("Gemini (%s)" % gemini.model if gemini.ready
                                      else "off (%s)" % gemini.problem)))
    print("Tap = dot, double tap = dash, pause = next letter, turn the wrist over = send. Ctrl+C stops.\n")

    demo = sim_script(a.demo, time.time() + 1, FACES.index(a.send_face)) if a.sim else []
    sent = {"done": False}
    if a.sim:
        spec_show = spec.show
        spec.show = lambda *x: (spec_show(*x), sent.update(done=True))

    shown = None
    try:
        while True:
            now = time.time()
            while demo and demo[0][0] <= now:
                _, kind, arg = demo.pop(0)
                band.transport.tap(kind, arg) if kind == "orientation" else band.transport.tap(kind)
            dec.tick(now)
            line = "  %s[%s]   (letter pause %.1fs)" % (dec.text, dec.current, dec.gaps[0])
            if line != shown:
                print("\r" + line.ljust(70), end="", flush=True)
                shown = line
            if a.sim and not demo and sent["done"]:
                voice.wait()
                break
            band.wait(0.05)
    except KeyboardInterrupt:
        print()
    finally:
        band.disconnect()


def sim_script(message, start, send_face, unit=0.3):
    """Pretend-band events that tap `message` like a quick, practised person, then send."""
    reverse = {v: k for k, v in MORSE.items()}
    events, t = [], start
    for word in message.upper().split():
        for ch in word:
            for symbol in reverse[ch]:
                events.append((t, "tap" if symbol == "." else "double-tap", 0))
                t += unit
            t += 4 * unit           # pause between letters
        t += 6 * unit               # pause between words: the voice is prepared here
    events += [(t - 0.4, "orientation", 4), (t, "orientation", send_face)]   # wrist over: send
    return events


if __name__ == "__main__":
    main()
