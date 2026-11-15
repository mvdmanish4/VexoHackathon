# Helen server, both directions:
#   taps on the band -> Morse -> AI sentence -> spoken out loud
#   someone speaks -> band mic -> Deepgram -> AI shortens -> Morse to feel
#   .venv/bin/python -m helen.main 46
import argparse
import json
import urllib.request
import random
import re
import threading
import time

from helen import phone
from helen.band import connect
from helen.compress import compress
from helen import agent, buzz, config
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
PHONE_MIC = config.get("PHONE_MIC", "0") == "1"       # the person talks into the phone (hold-to-talk)
agent_lock = threading.Lock()
SCRIPT = [QUICK_COUNT[n] for n in (1, 2, 3, 4)]
script_step = [0]


def sent(words):
    if IGNORE_BAND:
        return
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


def start_conversation():
    """Page button: Sri says her intro (line 1) and the script moves on from there."""
    with agent_lock:
        script_step[0] = 1
    log(">>> START button: Sri's intro")
    say_line(SCRIPT[0])


def reset_conversation():
    """Page button: back to the beginning, ready for the next take."""
    with agent_lock:
        script_step[0] = 0
        history.clear()
    log(">>> RESET button: script back to the start")
    phone.send({"type": "reset"})


def say_line(sentence):
    """Speak a fixed sentence (demo script). With a phone page open, the phone plays it
    (ElevenLabs voice); otherwise the laptop speaks."""
    try:
        log(f"<<< SAYING: {sentence}")
        history.append("Me: " + sentence)
        if phone.phones() or (VOICE_AGENT and PHONE_MIC):   # phone demo: never speak on the laptop
            say_on_phone(sentence)
            return
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
        listener.mute(len(mp3) / 16000 + 3.0)   # 128 kbit/s mp3 = 16 kB per second; + Deepgram's lag
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
    (r"\b(shree|shri|sri|sree|sheena|sriya)\b", "Shri"),
]


def fix_names(sentence):
    for pattern, name in NAME_FIXES:
        sentence = re.sub(pattern, name, sentence, flags=re.IGNORECASE)
    return sentence


IGNORE_BAND = config.get("IGNORE_BAND", "0") == "1"   # phone-only demo: band taps and mic do nothing


def heard(sentence):
    if IGNORE_BAND:
        return
    sentence = fix_names(sentence)
    if is_echo(sentence):
        log(f"--- ignored our own voice: {sentence}")
        return
    log(f"((( HEARD: {sentence}")
    last_band_heard[:] = [sentence, time.monotonic()]
    if VOICE_AGENT and PHONE_MIC:
        # The band hears the end of a sentence quickly even in a noisy room: tell the phone
        # to stop recording and send its turn now (it ignores this unless it is listening).
        phone.send({"type": "finish"})
        return
    phone.send({"type": "heard", "text": sentence})
    history.append("Them: " + sentence)
    if VOICE_AGENT:
        # Fallback when the phone can't listen (PHONE_MIC=0): the band's mic drives the same
        # dynamic conversation: buzz, 5-7 s pause, Sri's AI reply on the phone.
        threading.Thread(target=to_iphone, args=(sentence,), daemon=True).start()
        if len(sentence.split()) >= 3:
            threading.Thread(target=phone_turn, args=(sentence, True), daemon=True).start()
        return
    threading.Thread(target=feel, args=(sentence,), daemon=True).start()


def to_iphone(sentence):
    try:
        agent.vibrate_on_phone(sentence)
        log("    (sent to the iPhone app)")
    except Exception as e:
        log(f"!!! iPhone app server not reachable: {e}")


last_band_heard = ["", 0.0]   # latest sentence the band mic heard, as a fallback transcript


def spoke_into_phone(text):
    """Hold-to-talk on the phone was released: the person said their turn.
    Phone vibrates it -> 5-7 s pause -> Sri's AI reply plays on the phone."""
    if not text and time.monotonic() - last_band_heard[1] < 20:
        text = last_band_heard[0]                 # phone couldn't transcribe: use what the band heard
    text = fix_names(text) if text else ""
    log(f"((( HEARD (phone): {text or '(no words caught)'}")
    if text:
        history.append("Them: " + text)
        phone.send({"type": "heard", "text": text})
        threading.Thread(target=to_iphone, args=(text,), daemon=True).start()
    phone_turn(text)


def phone_audio(data, kind):
    """The phone recorded the person's turn: transcribe it with Deepgram, then carry on."""
    try:
        req = urllib.request.Request(
            "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&language=en",
            data, {"Authorization": "Token " + config.get("DEEPGRAM_API_KEY", ""),
                   "Content-Type": kind.split(";")[0] or "audio/mp4"})
        with urllib.request.urlopen(req, timeout=20) as r:
            result = json.load(r)
        text = result["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
    except Exception as e:
        log(f"!!! could not transcribe the phone recording ({len(data)} bytes): {e}")
        text = ""
    spoke_into_phone(text)


def phone_debug(message):
    log(f"    phone: {message}")


def phone_turn(text, from_band=False):
    if script_step[0] == 0:
        log("--- press Start conversation first")
        return
    if script_step[0] >= len(SCRIPT):
        return                                    # conversation already closed
    if not agent_lock.acquire(blocking=False):
        return                                    # Sri is still answering the last turn
    try:
        # Shri sticks to his script: his next line after each turn, then he closes.
        line = SCRIPT[min(script_step[0], len(SCRIPT) - 1)]
        reply = {"text": line}
        worker = threading.Thread(target=lambda: None)
        worker.start()                            # think while the phone buzzes and Sri "types"
        words = " ".join(sorted(re.findall(r"[A-Za-z0-9]+", text), key=len, reverse=True)[:2]).upper() or "HI"
        pulses = buzz.pattern(words, 2.0)
        phone.send({"type": "buzz", "words": words, "pattern": pulses})
        lo, _, hi = config.get("REPLY_PAUSE", "5-7").partition("-")   # seconds before Shri replies, e.g. "5-7" or "0"
        pause = random.uniform(float(lo), float(hi or lo))
        log(f">>> SRI: phone buzzes {buzz.length(pulses):.1f} s, then {pause:.1f} s pause, then answers")
        if pause:
            time.sleep(buzz.length(pulses) + pause)
        worker.join(timeout=10)
        say_line(reply.get("text") or "Sorry, could you say that again?")
        script_step[0] += 1
        if script_step[0] >= len(SCRIPT):
            log(">>> conversation finished")
            phone.send({"type": "end"})
    except Exception as e:
        log(f"!!! Sri could not answer: {e}")
    finally:
        agent_lock.release()


def agent_answer(sentence, force=False):
    """Voice-agent mode: after the person speaks, Sri waits 5-7 s (as if tapping) and says
    her next scripted line. One line per turn; anything said while she is waiting or
    speaking does not advance the script. After the last line she stops until a reset."""
    if not force and len(sentence.split()) < 3:
        return                       # a fragment or a cough, not a turn in the conversation
    if not agent_lock.acquire(blocking=False):
        return                       # already waiting or speaking: don't skip ahead
    try:
        step = script_step[0]
        if step == 0 or step >= len(SCRIPT):
            log("--- script: waiting for the intro tap" if step == 0 else "--- script finished (say reset to run again)")
            return
        # The phone buzzes what was heard for 5-7 s (Sri "feeling" it); Sri answers as it ends.
        key_words = " ".join(sorted(re.findall(r"[A-Za-z0-9]+", sentence), key=len, reverse=True)[:2]) or "HI"
        pulses = buzz.pattern(key_words.upper(), random.uniform(5.0, 7.0))
        pause = buzz.length(pulses)
        phone.send({"type": "buzz", "words": key_words.upper(), "pattern": pulses})
        log(f">>> SRI (voice agent): phone buzzes {pause:.1f} s, then line {step + 1}")
        time.sleep(pause + 0.3)
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


phone.on_action("start", start_conversation)
phone.on_action("reset", reset_conversation)
phone.on_action("spoke", spoke_into_phone)
phone.on_action("audio", phone_audio)
phone.on_action("debug", phone_debug)
address = phone.start()
log(f"PHONE: open {address} in Safari on the iPhone (same Wi-Fi as this laptop)")
if IGNORE_BAND:
    # Phone-only demo: don't connect to the band at all; the phone page does everything.
    log("PHONE ONLY: not connecting to the band (IGNORE_BAND=1)")
    if VOICE_AGENT:
        log(f"VOICE AGENT ON: phone mic -> Shri replies on the phone, pause {config.get('REPLY_PAUSE', '5-7')} s")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    raise SystemExit
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
