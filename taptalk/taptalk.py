"""TapTalk: a deaf-blind, non-speaking person taps Morse on the Vexo band; the laptop speaks it.

    single tap = dot         double tap = dash
    short pause = next letter    longer pause = space   (pauses adapt to your speed)
    6 or more dots = delete the last letter
    turn the wrist over and hold it = send      or stay still a few seconds = send

Taps are found in the band's raw accelerometer (833 readings a second), not with the band's
own double-tap, which often splits one double tap into two taps. Gemini turns short taps
into a full sentence, ElevenLabs speaks it in a human voice (both optional: see README).
Run in this folder:

    python3 taptalk.py --band N --calibrate  first time: learns your tap rhythm (30 s)
    python3 taptalk.py --band N              your band (N is the number on the band's bag)
    python3 taptalk.py --band N --sim        the pretend band taps "HELP ME" and sends it
    python3 taptalk.py --band N --debug      also print every tap and what it became
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "vexo-open-kit" / "python"))
from vexo_open.sync import Band  # noqa: E402
from vexo_open.transports.sim import SimTransport  # noqa: E402

from morse import MORSE, TapDecoder  # noqa: E402
from sponsors import Gemini, Speculator, Voice  # noqa: E402
from taps import TapClassifier, TapDetector, WristTurn, calibrate  # noqa: E402

FACES = ["+x", "-x", "+y", "-y", "+z", "-z"]
TURN_TAIL = 0.25     # s: a tap this soon before the wrist starts turning came from the turn


def parse_args():
    p = argparse.ArgumentParser(description="Tap Morse on the Vexo band; the laptop speaks it.")
    p.add_argument("--band", type=int, required=True,
                   help="your team's band number, printed on the band's bag (7 = Vexo-HACK-07)")
    p.add_argument("--sim", action="store_true", help="use the pretend band and tap a demo message")
    p.add_argument("--demo", default="HELP ME", help="what the pretend band taps with --sim (letters, digits, spaces)")
    p.add_argument("--debug", action="store_true", help="print every tap and what it became")
    p.add_argument("--calibrate", action="store_true",
                   help="learn your tap rhythm: tap 5 single taps, then 5 double taps")
    p.add_argument("--detector", default=None, choices=["raw", "band"],
                   help="raw = find taps in the accelerometer (default); band = the band's own tap "
                        "events (default with --sim; --sim --detector raw plays the demo as raw motion)")
    p.add_argument("--double-window", type=float, default=0.30,
                   help="two taps closer than this (s) are one double tap = dash (set it with --calibrate)")
    p.add_argument("--tap-g", type=float, default=1.0,
                   help="raw detector: how hard a tap must be, in g (lower = lighter taps count)")
    p.add_argument("--no-ai", action="store_true", help="speak the tapped letters as they are (no Gemini)")
    p.add_argument("--no-eleven", action="store_true", help="use the Mac's voice, not ElevenLabs")
    p.add_argument("--letter-gap", type=float, default=1.2, help="starting pause (s) that ends a letter")
    p.add_argument("--word-gap", type=float, default=2.6, help="starting pause (s) that ends a word")
    p.add_argument("--send-gap", type=float, default=6.0, help="starting pause (s) that sends (0 = off)")
    p.add_argument("--fixed", action="store_true", help="keep the pauses fixed (do not adapt to the tapper)")
    p.add_argument("--no-speculate", action="store_true", help="do not prepare the voice while tapping")
    p.add_argument("--dedup", type=float, default=0,
                   help="band detector only: drop a dot this many seconds before a dash, e.g. 0.3")
    p.add_argument("--tap-threshold", type=float, default=0.8,
                   help="band detector only: tap strength in g, 0.2..8")
    p.add_argument("--send-face", default="+z", choices=FACES,
                   help="band detector only: the face pointing up that means 'send'")
    a = p.parse_args()
    if a.sim and not all(c in MORSE.values() or c == " " for c in a.demo.upper()):
        p.error("--demo can only use letters A-Z, digits and spaces")
    if not 1 <= a.band <= 999:
        p.error("--band must be your band's number, 1 to 999")
    if not 0.1 <= a.double_window <= 1.0:
        p.error("--double-window must be between 0.1 and 1.0 seconds")
    if not 0.2 <= a.tap_g <= 8:
        p.error("--tap-g must be between 0.2 and 8")
    if a.sim:
        if a.calibrate:
            p.error("--calibrate needs the real band")
    a.detector = a.detector or ("band" if a.sim else "raw")
    return a


def start_motion(band):
    """The fastest accelerometer stream this link allows (833 a second over Bluetooth)."""
    limits = band.motion_limits()
    sensors = "accel" if limits.accel else "both"     # firmware 1.0 has no accel-only stream
    try:
        band.set_motion(accel_range=8)                # hard taps do not clip
    except Exception as e:                            # not fatal: the default range still works
        print("  (could not set the 8 g range: %s)" % e)
    streams = band.configure(motion="fastest", sensors=sensors)
    return streams.get("motion")


def run_calibration(band, a, voice):
    taps = []
    det = TapDetector(threshold=min(a.tap_g, 0.6), on_tap=lambda t, s: taps.append((t, s)))

    def on_motion(m):
        if m.ax is not None:
            det.feed(m.time, m.ax, m.ay, m.az)

    band.on("motion", on_motion)
    rate = start_motion(band)
    print("Reading the accelerometer %s times a second.\n" % rate)

    def phase(prompt, seconds):
        print("  " + prompt)
        voice.say(prompt)
        voice.wait()
        start = time.time()
        band.wait(seconds)
        got = [(t, s) for t, s in taps if t >= start]
        print("    felt %d taps" % len(got))
        return got

    singles = phase("Tap five single taps, slowly, like separate dots.", 9)
    voice.say("Good.")
    doubles = phase("Now five double taps, like dashes.", 10)
    window, rep = calibrate([t for t, _ in singles], [t for t, _ in doubles])
    strengths = [s for _, s in singles + doubles]
    tap_g = max(0.3, round(0.5 * statistics.median(strengths), 1)) if strengths else a.tap_g

    print()
    if window is None:
        print("  Calibration failed: %s. Run it again, tapping a little harder." % rep["why"])
        voice.say("Calibration failed. Please try again.")
    else:
        print("  Double tap gap: %.2f s typical, %.2f s slowest" % (rep["double_gap"], rep["slowest_double"]))
        print("  Gap between single taps: %.2f s typical, %.2f s quickest" % (rep["dot_gap"], rep["fastest_dot"]))
        print("  Tap strength: %.1f g typical" % statistics.median(strengths))
        if not rep["ok"]:
            print("  Warning: %s." % rep["why"])
        print("\n  Use:  python3 taptalk.py --band %d --double-window %.2f --tap-g %.1f\n"
              % (a.band, window, tap_g))
        voice.say("Done. Double tap window %d milliseconds." % round(window * 1000))
    voice.wait()


def main():
    a = parse_args()
    raw = a.detector == "raw"
    voice = Voice(use_eleven=not a.no_eleven and not a.calibrate, debug=a.debug)

    transport = SimTransport(a.band, auto_tap=False) if a.sim else None
    print("Connecting to Vexo-HACK-%02d ... (double-tap the band first if it is not blinking blue)" % a.band)
    band = Band.connect(a.band, transport=transport) if a.sim else Band.connect(a.band, auto_reconnect=True)
    print("Connected to %s." % band.name)

    if a.calibrate:
        try:
            run_calibration(band, a, voice)
        finally:
            band.disconnect()
        return

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

    # With our own detector a dot is decided double_window after its tap, so the letter
    # pause must stay well above that window.
    dec = TapDecoder(letter_gap=a.letter_gap, word_gap=a.word_gap, send_gap=a.send_gap,
                     dedup=0 if raw else a.dedup, adaptive=not a.fixed,
                     min_letter_gap=max(0.6, 2.5 * a.double_window) if raw else 0.6,
                     on_letter=on_letter, on_delete=on_delete, on_word=on_word, on_message=on_message)

    classifier = setup_raw(band, a, dec) if raw else setup_band_events(band, a, dec)

    print("Voice: %s.  Sentence help: %s." % (
        voice.engine,
        "off" if gemini is None else ("Gemini (%s)" % gemini.model if gemini.ready
                                      else "off (%s)" % gemini.problem)))
    print("Tap = dot, double tap = dash, pause = next letter, turn the wrist over and hold = send. "
          "Ctrl+C stops.\n")

    demo = []
    if a.sim and raw:
        band.transport.play_motion(sim_motion(a.demo))
    elif a.sim:
        demo = sim_script(a.demo, time.time() + 1, FACES.index(a.send_face))
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
            if classifier:
                classifier.tick(now)
                waiting = classifier.pending
                # A tap that may still become a dash is activity: do not end the letter early.
                dec.tick(now if waiting is None else min(now, waiting))
            else:
                dec.tick(now)
            line = "  %s[%s]   (letter pause %.1fs)" % (dec.text, dec.current, dec.gaps[0])
            if line != shown:
                print("\r" + line.ljust(70), end="", flush=True)
                shown = line
            if a.sim and not demo and sent["done"]:
                voice.wait()
                break
            band.wait(0.02)
    except KeyboardInterrupt:
        print()
    finally:
        band.disconnect()


def setup_raw(band, a, dec):
    """Taps and the send gesture from the raw accelerometer. Returns the classifier."""
    last = {"tap": None}

    def log(msg):
        if a.debug:
            print("\n  [tap] " + msg)

    def on_dot(t):
        dec.dot(t)
        log("-> dot  .")

    def on_dash(t):
        dec.dash(t)
        log("-> dash -   (two taps)")

    classifier = TapClassifier(a.double_window, on_dot=on_dot, on_dash=on_dash)

    def on_send():
        classifier.cancel()
        dec.request_send()
        log("wrist turned over and held: send")

    def on_turn_start(t):
        p = classifier.pending
        if p is not None and t - p < TURN_TAIL:
            classifier.cancel()               # that "tap" was the start of the turn
            log("dropped a tap made by turning the wrist")

    wrist = WristTurn(on_send=on_send, on_turn_start=on_turn_start)

    def on_tap(t, strength):
        gap = "" if last["tap"] is None else "  +%.2f s" % (t - last["tap"])
        if wrist.turning:
            log("%.1f g%s ignored: the wrist is turned (%d deg)" % (strength, gap, wrist.angle))
            return
        last["tap"] = t
        wrist.note_tap()
        log("%.1f g%s" % (strength, gap))
        classifier.tap(t)

    def on_reject(t, strength, width):
        log("movement %.1f g for %d ms: not a tap" % (strength, width * 1000))

    det = TapDetector(threshold=a.tap_g, on_tap=on_tap, on_reject=on_reject if a.debug else None)

    def on_motion(m):
        if m.ax is not None:
            wrist.feed(m.time, m.ax, m.ay, m.az)
            det.feed(m.time, m.ax, m.ay, m.az)

    band.on("motion", on_motion)
    rate = start_motion(band)
    print("Finding taps in the accelerometer (%s readings a second, double tap under %.2f s, "
          "taps over %.1f g)." % (rate, a.double_window, a.tap_g))
    return classifier


def setup_band_events(band, a, dec):
    """The band's own tap / double-tap / orientation events (the pretend band, or --detector band)."""
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
    return None


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
    before = 1 if send_face == 0 else 0     # any other face first, then the send face
    events += [(t - 0.4, "orientation", before), (t, "orientation", send_face)]
    return events


def sim_motion(message, unit=0.4, double_gap=0.16, rate=833):
    """Raw accelerometer samples for the pretend band: `message` tapped as sharp jolts (a
    double tap is two jolts double_gap apart), then the wrist turned over and held."""
    import math
    reverse = {v: k for k, v in MORSE.items()}
    taps, t = [], 1.0
    for word in message.upper().split():
        for ch in word:
            for symbol in reverse[ch]:
                taps.append(t)
                if symbol == "-":
                    taps.append(t + double_gap)
                t += unit + (double_gap if symbol == "-" else 0)
            t += 3 * unit
        t += 4 * unit
    turn_at, total = t, t + 2.5
    samples = []
    for i in range(int(total * rate)):
        s = i / rate
        z = 1.0
        for tt in taps:
            d = s - tt
            if 0 <= d < 0.04:
                z += 2.5 * math.exp(-d / 0.006) * math.cos(2 * math.pi * 150 * d)
        a = math.pi * min(1.0, max(0.0, (s - turn_at) / 0.3))
        samples.append(dict(ax=math.sin(a), ay=0.0, az=z - 1 + math.cos(a)))
    return samples


if __name__ == "__main__":
    main()
