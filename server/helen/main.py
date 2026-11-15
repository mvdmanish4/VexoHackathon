# Helen server, both directions:
#   taps on the band -> Morse -> AI sentence -> spoken out loud
#   someone speaks -> band mic -> Deepgram -> AI shortens -> Morse to feel
#   .venv/bin/python -m helen.main 46
import argparse
import random
import re
import threading
import time

from helen import phone
from helen.band import connect
from helen.compress import compress
from helen import agent, config
from helen.expand import QUICK_COUNT, expand, quick
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


# Demo mode (DEMO_SCRIPT=1 in .env): every send plays the next line of the script, whatever
# was tapped, so the demo can't be thrown off by a misread tap. After the last line it
# starts again.
DEMO_SCRIPT = config.get("DEMO_SCRIPT", "0") == "1"
VOICE_AGENT = config.get("VOICE_AGENT", "0") == "1"   # AI "Sri" answers whoever talks (helen/agent.py)
agent_lock = threading.Lock()
SCRIPT = [QUICK_COUNT[n] for n in (1, 2, 3, 4)]
script_step = [0]


def sent(words):
    if VOICE_AGENT:
        # Taps are only acted out on camera: the first one plays Sri's intro, the AI does the rest.
        if script_step[0] == 0:
            script_step[0] = 1
            log(f">>> TAPPED: {words}   (voice agent: intro)")
            threading.Thread(target=say_line, args=(SCRIPT[0],), daemon=True).start()
        else:
            log(f"--- tap ignored in voice-agent mode: {words}")
        return
    if DEMO_SCRIPT:
        line = SCRIPT[script_step[0] % len(SCRIPT)]
        log(f">>> TAPPED: {words}   (demo script line {script_step[0] % len(SCRIPT) + 1})")
        script_step[0] += 1
        threading.Thread(target=say_line, args=(line,), daemon=True).start()
        return
    words = " ".join(w.replace("?", "") for w in words.split()).strip()   # "?" = not a letter: noise
    if not words:
        log("--- ignored: only unreadable taps")
        return
    if is_stray(words):
        log(f"--- ignored stray taps: {words}")
        return
    log(f">>> TAPPED: {words}")
    threading.Thread(target=say, args=(words,), daemon=True).start()


def say_line(sentence):
    """Speak a fixed sentence (demo script), the same way say() does after the AI step."""
    try:
        log(f"<<< SAYING: {sentence}")
        history.append("Me: " + sentence)
        phone.send({"type": "say", "text": sentence})
        if listener:
            listener.mute(30)
        speak(sentence)
        if listener:
            listener.muted_until = time.monotonic() + 3.0
    except Exception as e:
        log(f"!!! could not speak: {e}")


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
            listener.muted_until = time.monotonic() + 3.0   # Deepgram finishes a sentence late
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


def words_of(text):
    return {w.strip(".,!?'\"").lower() for w in text.split()} - {""}


def is_echo(sentence):
    """The band's mic hearing our own voice: mostly the same words as something we just said."""
    heard_words = words_of(sentence)
    for said in [h[4:] for h in history[-3:] if h.startswith("Me: ")]:
        said_words = words_of(said)
        if heard_words and said_words and len(heard_words & said_words) >= 0.6 * len(heard_words):
            return True
    return False


# Names speech-to-text gets wrong in our demo, and what they should be.
NAME_FIXES = [
    (r"\b(five|5|pipe|pi?pe?)[ -]?cats?\b", "Pipecat"),
    (r"\b(pipette|pipe it|pipe ?cut|pipe ?kat|pipe ?guide|pipe ?gate)\b", "Pipecat"),
    (r"\b(11|eleven|lemon|level)[ -]?labs?\b", "ElevenLabs"),
    (r"\bday[ -]?break\b", "Daybreak"),
    (r"\b(shree|shri|sree|sheena|sriya)\b", "Sri"),
]


def fix_names(sentence):
    for pattern, name in NAME_FIXES:
        sentence = re.sub(pattern, name, sentence, flags=re.IGNORECASE)
    return sentence


def heard(sentence):
    sentence = fix_names(sentence)
    if is_echo(sentence):
        log(f"--- ignored our own voice: {sentence}")
        return
    log(f"((( HEARD: {sentence}")
    phone.send({"type": "heard", "text": sentence})
    history.append("Them: " + sentence)
    if VOICE_AGENT:
        threading.Thread(target=to_iphone, args=(sentence,), daemon=True).start()
        threading.Thread(target=agent_answer, args=(sentence,), daemon=True).start()
    threading.Thread(target=feel, args=(sentence,), daemon=True).start()


def to_iphone(sentence):
    try:
        agent.vibrate_on_phone(sentence)
        log("    (sent to the iPhone app)")
    except Exception as e:
        log(f"!!! iPhone app server not reachable: {e}")


def agent_answer(sentence):
    """Voice-agent mode: after the person speaks, Sri waits 5-7 s (as if tapping) and says
    her next scripted line. One line per turn; anything said while she is waiting or
    speaking does not advance the script. After the last line she stops until a reset."""
    if len(sentence.split()) < 3:
        return                       # a fragment or a cough, not a turn in the conversation
    if not agent_lock.acquire(blocking=False):
        return                       # already waiting or speaking: don't skip ahead
    try:
        step = script_step[0]
        if step == 0 or step >= len(SCRIPT):
            log("--- script: waiting for the intro tap" if step == 0 else "--- script finished (say reset to run again)")
            return
        pause = random.uniform(5.0, 7.0)
        log(f">>> SRI (voice agent) answers line {step + 1} in {pause:.1f} s")
        time.sleep(pause)
        script_step[0] = step + 1
        say_line(SCRIPT[step])
    except Exception as e:
        log(f"!!! voice agent failed: {e}")
    finally:
        agent_lock.release()


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
if VOICE_AGENT:
    log(f"VOICE AGENT ON: Sri answers whoever talks; heard sentences go to the iPhone app at {agent.IOS_SERVER}")
if DEMO_SCRIPT:
    log("DEMO SCRIPT ON: each send plays the next line: " + " | ".join(SCRIPT))
try:
    band.wait(4 * 3600)
except KeyboardInterrupt:
    pass
band.disconnect()
