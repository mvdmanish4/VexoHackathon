# Helen server, both directions:
#   taps on the band -> Morse -> AI sentence -> spoken out loud
#   someone speaks -> band mic -> Deepgram -> AI shortens -> Morse to feel
#   .venv/bin/python -m helen.main 46
import argparse
import threading
import time

from helen import phone
from helen.band import connect
from helen.compress import compress
from helen.expand import expand, quick
from helen.listen import Listener
from helen.morse import encode
from helen.taps import TapReader
from helen.voice import speak, synthesize

parser = argparse.ArgumentParser()
parser.add_argument("number", nargs="?", type=int, default=None)
parser.add_argument("--sim", action="store_true")
args = parser.parse_args()

history = []   # recent lines of the conversation, so the AI has context
listener = None


def log(line):
    stamped = f"{time.strftime('%H:%M:%S')} {line}"
    print(stamped, flush=True)
    if not line.startswith("mic:"):              # the 10-second mic health lines are just noise there
        phone.send({"type": "log", "line": stamped})


def changed(event, text):
    log(f"  [{event:<6}] text: {text}")


def is_stray(words):
    """Only loose single letters that are not a quick phrase: accidental bumps, not a message."""
    return not quick(words) and all(len(w) == 1 for w in words.split())


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
        phone.send({"type": "say", "text": sentence})   # pages show it; the laptop speaks it
        if listener:
            listener.mute(30)            # don't transcribe our own voice
        speak(sentence)
        if listener:
            listener.muted_until = time.monotonic() + 0.5
    except Exception as e:   # keep the server alive whatever the AI or voice service does
        log(f"!!! could not speak: {e}")


def say_on_phone(sentence):
    """Play the voice on the phone (falls back to showing the text if ElevenLabs fails)."""
    try:
        mp3 = synthesize(sentence)
    except Exception as e:
        log(f"!!! ElevenLabs failed ({e}), phone shows text only; laptop speaks")
        phone.send({"type": "say", "text": sentence})
        speak(sentence)
        return
    if listener:
        listener.mute(len(mp3) / 16000 + 1.5)   # 128 kbit/s mp3 = 16 kB per second
    phone.send({"type": "say", "text": sentence, "audio": phone.add_audio(mp3)})
    log("    (voice sent to the phone)")


def heard(sentence):
    log(f"((( HEARD: {sentence}")
    phone.send({"type": "heard", "text": sentence})
    history.append("Them: " + sentence)
    threading.Thread(target=feel, args=(sentence,), daemon=True).start()


def feel(sentence):
    try:
        words = compress(sentence)
        log(f"~~~ FEEL: {words}   {encode(words)}")
        phone.send({"type": "feel", "words": words, "morse": encode(words)})
    except Exception as e:
        log(f"!!! could not shorten: {e}")


address = phone.start()
log(f"PHONE: open {address} in Safari on the iPhone (same Wi-Fi as this laptop)")
band = connect(args.number, args.sim)
log(f"Connected to {band.name}")
band.on("disconnect", lambda e: log(f"!!! band disconnected: {getattr(e, 'reason', e)}"))
band.on("reconnecting", lambda e: log("!!! band connection lost, reconnecting (double-tap the band if it takes long)"))
band.on("reconnected", lambda e: log("!!! band reconnected"))
TapReader(band, sent, changed)
try:
    listener = Listener(band, heard, log)
    log("Listening: the band's mic is on (blue light), speech goes to Deepgram.")
except Exception as e:
    log(f"!!! not listening (taps still work): {e}")
log("Ready: tap Morse, turn wrist over and hold 2s to speak. Ctrl+C to stop.")
try:
    band.wait(4 * 3600)
except KeyboardInterrupt:
    pass
band.disconnect()
