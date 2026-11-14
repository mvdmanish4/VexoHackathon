"""The sponsor services TapTalk uses, each with a safe offline fallback, tuned for speed.

- Gemini: turns short tapped Morse ("WTR") into the sentence the person most likely means.
  Skipped when every tapped word is already a real word, so "HI" or "HELP" costs no wait.
- ElevenLabs: speaks the message in a natural human voice. Sound plays inside this program
  (no player program to start), which on a busy Mac saves 1.5-4 s per sound.
- Speculator: while the person is still tapping, each finished word starts the Gemini and
  ElevenLabs work for the text so far, so on send the voice is usually ready at once.

Keys are read from the environment or from a `.env` file in the folder the program is
started in (GEMINI_API_KEY, ELEVENLABS_API_KEY). They are never printed, logged or written.
Without a key, or with no internet, the raw letters are used and the Mac's built-in voice
(`say`) speaks instead, so the demo always works.
"""
import json
import os
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _SSL = ssl.create_default_context()

def find_key(name):
    """A key from the environment, else from ./.env. Never print what this returns."""
    found = os.environ.get(name, "").strip()
    if not found:
        try:
            with open(os.path.join(os.getcwd(), ".env"), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("export "):
                        line = line[7:]
                    key, _, value = line.partition("=")
                    if key.strip() == name and value.strip():
                        found = value.strip().strip("'\"")
        except OSError:
            pass
    return found


def _request(url, body, headers, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    return urllib.request.urlopen(req, timeout=timeout, context=_SSL)


# ---- Real words need no AI ---------------------------------------------------------------

_WORDS = None


def is_plain_words(text):
    """True when every tapped word is a dictionary word, so Gemini can be skipped."""
    global _WORDS
    if _WORDS is None:
        try:
            with open("/usr/share/dict/words", encoding="utf-8") as f:
                _WORDS = {w.strip().upper() for w in f if len(w.strip()) > 1}
        except OSError:
            _WORDS = set()
        _WORDS |= {"I", "A", "OK", "HI", "NO", "YES", "SOS"}
    words = text.upper().split()
    return bool(words) and all(w in _WORDS for w in words)


# ---- Gemini: short taps -> full sentence -------------------------------------------------

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

EXPAND_INSTRUCTIONS = (
    "A deaf-blind person who cannot speak typed the message below by tapping Morse code. "
    "Tapping is slow, so they use short words and abbreviations (WTR = water, PLS = please, "
    "THX = thanks, HLP = help) and sometimes mistype one letter. Write the one short, "
    "natural first-person sentence they most likely mean, as they would say it out loud. "
    "Keep their meaning exactly: never add facts, names, numbers or requests they did not tap. "
    "If it is unclear, return their letters as plain words. Output only the sentence."
)


# Gemini 4 first (the sponsor track), fastest first as measured on 2026-11-14:
# hydrogen ~2.2 s, argon ~3.7 s, carbon ~4.9 s per answer. Then the newest flash model.
GEMINI_PREFERENCE = ["gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon"]

# Ways to ask a model to answer without long thinking, tried in order until one works.
# Older models take thinkingBudget 0; Gemini 4 refuses that or ignores it and wants a level.
THINKING_STYLES = [
    {"maxOutputTokens": 60, "thinkingConfig": {"thinkingBudget": 0}},
    {"maxOutputTokens": 600, "thinkingConfig": {"thinkingLevel": "low"}},
    {"maxOutputTokens": 600},
]


class Gemini:
    def __init__(self, model=None):
        self.key = find_key("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", "").strip() or None
        self.problem = None if self.key else "no GEMINI_API_KEY"
        self._style = 0                    # index into THINKING_STYLES that works for this model
        self._lock = threading.Lock()
        if self.key and not self.model:
            self.model = self._pick_model()

    @property
    def ready(self):
        return bool(self.key and self.model and not self.problem)

    def warm_up(self):
        """In the background, find how this model answers fast, so the first message is quick."""
        if self.ready:
            threading.Thread(target=self.expand, args=("OK",), daemon=True).start()

    def _pick_model(self):
        """A Gemini 4 model if the key has one, else the newest Gemini flash model."""
        try:
            req = urllib.request.Request(GEMINI_BASE + "/models?pageSize=200",
                                         headers={"x-goog-api-key": self.key})
            with urllib.request.urlopen(req, timeout=10, context=_SSL) as r:
                models = json.load(r).get("models", [])
        except urllib.error.HTTPError as e:
            self.problem = "Gemini model list failed (status %d)" % e.code
            return None
        except (urllib.error.URLError, OSError, ValueError):
            self.problem = "could not reach Gemini"
            return None
        names = [m["name"].split("/", 1)[-1] for m in models
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        for preferred in GEMINI_PREFERENCE:
            if preferred in names:
                return preferred
        flash = [n for n in names if n.startswith("gemini-") and "flash" in n
                 and not any(w in n for w in ("image", "tts", "live", "audio"))]
        if not flash:
            self.problem = "no Gemini model available to this key"
            return None

        def rank(n):
            try:
                version = tuple(int(p) for p in n.split("-")[1].split("."))
            except ValueError:
                version = (0,)
            return version, "preview" not in n and "exp" not in n
        return max(flash, key=rank)

    def expand(self, letters):
        """The sentence the person most likely means, or None if Gemini can't help now."""
        if not self.ready:
            return None
        with self._lock:
            style = self._style
        while style < len(THINKING_STYLES):
            config = {"temperature": 0.2, **THINKING_STYLES[style]}
            body = {
                "systemInstruction": {"parts": [{"text": EXPAND_INSTRUCTIONS}]},
                "contents": [{"role": "user", "parts": [{"text": letters}]}],
                "generationConfig": config,
            }
            try:
                with _request("%s/models/%s:generateContent" % (GEMINI_BASE, self.model), body,
                              {"x-goog-api-key": self.key}, timeout=10) as r:
                    candidate = json.load(r)["candidates"][0]
                parts = candidate.get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                text = text.strip().strip('"')
                if text:
                    with self._lock:
                        self._style = style    # remember what works for the next message
                    return text
                if candidate.get("finishReason") != "MAX_TOKENS":
                    return None
                # it spent the whole answer thinking: ask the next way
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    print("\n  (Gemini said status %d; using the tapped letters)" % e.code)
                    return None
                # 400: this model does not take that setting: ask the next way
            except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
                print("\n  (Gemini not reachable; using the tapped letters)")
                return None
            style += 1
        print("\n  (Gemini gave no answer; using the tapped letters)")
        return None


# ---- Playback: one audio engine kept open, so nothing waits for a program to start ------

class MacAudio:
    """macOS speech and sound inside this program (PyObjC / AppKit).

    Starting `say` or `afplay` costs 1.5-4 s per sound on a busy Mac; this costs ~20 ms after
    a one-time warm-up. Create and use it on one thread only (the Voice thread).
    """

    def __init__(self):
        from AppKit import NSSound, NSSpeechSynthesizer
        from Foundation import NSData, NSDate, NSRunLoop
        self._NSSound, self._NSData, self._NSDate, self._NSRunLoop = NSSound, NSData, NSDate, NSRunLoop
        self._syn = NSSpeechSynthesizer.alloc().initWithVoice_(None)
        self._syn.setVolume_(0.0)                     # warm up silently: the first word is slow
        self.speak("ready", 300)
        self._syn.setVolume_(1.0)

    def _pump(self):
        self._NSRunLoop.currentRunLoop().runUntilDate_(self._NSDate.dateWithTimeIntervalSinceNow_(0.02))

    def speak(self, text, rate, interrupted=lambda: False):
        self._syn.setRate_(rate)
        self._syn.startSpeakingString_(text)
        while self._syn.isSpeaking():
            if interrupted():
                self._syn.stopSpeaking()
                return
            self._pump()

    def play(self, data):
        sound = self._NSSound.alloc().initWithData_(self._NSData.dataWithBytes_length_(data, len(data)))
        if sound is None or not sound.play():
            raise OSError("could not play the audio")
        # Off the main thread NSSound never reports that it stopped, so wait for its length.
        deadline = time.time() + sound.duration() + 0.15
        while time.time() < deadline:
            self._pump()
        sound.stop()


class ProcessAudio:
    """Fallback without PyObjC: the `say` and `afplay` programs (slower to start)."""

    def speak(self, text, rate, interrupted=lambda: False):
        subprocess.run(["say", "-r", str(rate), text], check=False)

    def play(self, data):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            subprocess.run(["afplay", path], check=False)
        finally:
            os.unlink(path)


# ---- ElevenLabs + the voice thread -------------------------------------------------------

ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/%s?output_format=mp3_22050_32"
CUE_RATE, MESSAGE_RATE = 260, 190     # words per minute for the local voice


class Voice:
    """Plays one thing at a time on its own thread, so taps are never blocked.

    say(text) is a short cue (a letter, "deleted") in the instant local voice.
    message(text, audio=None, t_send=None) is the real message: it skips any cues still
    waiting, and plays ready-made audio if given, else ElevenLabs, else the local voice.
    """

    def __init__(self, use_eleven=True, debug=False):
        self.key = find_key("ELEVENLABS_API_KEY") if use_eleven else ""
        self.voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or "21m00Tcm4TlvDq8ikWAM"
        self.model = os.environ.get("ELEVENLABS_MODEL", "").strip() or "eleven_flash_v2_5"
        self.debug = debug
        self.audio_kind = None
        self._items = deque()
        self._cv = threading.Condition()
        self._busy = True                              # until the audio engine is warm
        threading.Thread(target=self._run, daemon=True).start()
        self.wait()

    @property
    def engine(self):
        return "%s, %s audio" % ("ElevenLabs" if self.key else "Mac voice", self.audio_kind)

    def say(self, text, quick=True):
        if text:
            with self._cv:
                self._items.append(("cue", text, None, None))
                self._cv.notify()

    def message(self, text, audio=None, t_send=None):
        if text:
            with self._cv:
                kept = [i for i in self._items if i[0] != "cue"]   # the message jumps the cues
                self._items.clear()
                self._items.extend(kept)
                self._items.append(("msg", text, audio, t_send))
                self._cv.notify()

    def wait(self):
        with self._cv:
            while self._items or self._busy:
                self._cv.wait(0.1)

    def render(self, text):
        """The whole ElevenLabs mp3 for text, or None (no key, or the service failed)."""
        if not self.key:
            return None
        try:
            with _request(ELEVEN_URL % self.voice_id, {"text": text, "model_id": self.model},
                          {"xi-api-key": self.key, "Accept": "audio/mpeg"}, timeout=20) as r:
                return r.read() or None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self.key = ""                  # the key is wrong or switched off: stop trying
                print("\n  (ElevenLabs refused the key, status %d; the Mac voice is used from now on)" % e.code)
            else:
                print("\n  (ElevenLabs said status %d; using the Mac voice)" % e.code)
        except (urllib.error.URLError, OSError):
            print("\n  (ElevenLabs not reachable; using the Mac voice)")
        return None

    def _run(self):
        try:
            self._audio = MacAudio()
            self.audio_kind = "in-process"
        except Exception:                              # no PyObjC, or not a Mac session
            self._audio = ProcessAudio()
            self.audio_kind = "say/afplay"
        with self._cv:
            self._busy = False
            self._cv.notify_all()
        while True:
            with self._cv:
                while not self._items:
                    self._cv.wait()
                kind, text, audio, t_send = self._items.popleft()
                self._busy = True
            try:
                if kind == "cue":       # a waiting message cuts a letter cue short
                    self._audio.speak(text, CUE_RATE, interrupted=self._message_waiting)
                else:
                    self._play_message(text, audio, t_send)
            except Exception as e:                     # never let one sound stop the voice
                print("\n  (could not play a sound: %s)" % e)
            finally:
                with self._cv:
                    self._busy = False
                    self._cv.notify_all()

    def _message_waiting(self):
        with self._cv:
            return any(i[0] == "msg" for i in self._items)

    def _report(self, path, t_send):
        if self.debug and t_send is not None:
            print("\n  [speed] send -> sound in %d ms (%s)" % ((time.time() - t_send) * 1000, path))

    def _play_message(self, text, audio, t_send):
        path = "ElevenLabs, prepared while tapping"
        if not audio and self.key:
            audio, path = self.render(text), "ElevenLabs, made after send"
        if audio:
            try:
                self._report(path, t_send)
                self._audio.play(audio)
                return
            except OSError as e:
                print("\n  (%s; using the Mac voice)" % e)
        self._report("Mac voice", t_send)
        self._audio.speak(text, MESSAGE_RATE)


# ---- Speculator: do the slow work while the person is still tapping ------------------------

class Speculator:
    """prepare(text) at each word break; finish(text) on send.

    One worker thread works out (sentence, audio) for the newest text only. If finish() asks
    for the text that is ready or being worked on, nothing is redone.
    """

    def __init__(self, gemini, voice, show=print):
        self.gemini = gemini
        self.voice = voice
        self.show = show
        self._cache = {}              # text -> (sentence, audio or None)
        self._pending = None          # newest text waiting to be prepared
        self._working = None          # text being prepared right now
        self._final = None            # (text, t_send) to play as soon as it is ready
        self._cv = threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()

    def prepare(self, text):
        text = text.strip()
        with self._cv:
            if text and text not in self._cache and text != self._working:
                self._pending = text  # replaces any older pending text
                self._cv.notify()

    def finish(self, text, t_send):
        text = text.strip()
        with self._cv:
            if text in self._cache:
                ready = self._cache[text]
            else:
                ready = None
                self._final = (text, t_send)
                if text != self._working:
                    self._pending = text
                self._cv.notify()
        if ready:
            self._play(text, ready, t_send)

    def _sentence(self, text):
        if is_plain_words(text) or not (self.gemini and self.gemini.ready):
            return None
        return self.gemini.expand(text)

    def _run(self):
        while True:
            with self._cv:
                while self._pending is None:
                    self._cv.wait()
                text, self._pending = self._pending, None
                self._working = text
            sentence = self._sentence(text)
            spoken = sentence or text.lower()
            # Prepared audio only pays off with ElevenLabs (render() is None without a key).
            audio = self.voice.render(spoken)
            with self._cv:
                self._cache[text] = (sentence, audio)
                self._working = None
                final = self._final if self._final and self._final[0] == text else None
                if final:
                    self._final = None
            if final:
                self._play(text, (sentence, audio), final[1])

    def _play(self, text, ready, t_send):
        sentence, audio = ready
        self.show(text, sentence)
        self.voice.message(sentence or text.lower(), audio=audio, t_send=t_send)
