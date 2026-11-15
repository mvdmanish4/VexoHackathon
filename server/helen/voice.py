"""Voice step: turns a sentence into speech with ElevenLabs and plays it."""
import json
import subprocess
import tempfile
import urllib.request

from helen import config

DEFAULT_VOICE = "SAz9YHcvj6GT2YYXdXww"   # ElevenLabs premade voice "River" (free accounts can use premade voices only)


def synthesize(text):
    """Returns MP3 bytes for `text`."""
    voice = config.get("ELEVENLABS_VOICE_ID", DEFAULT_VOICE)
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
           "?output_format=mp3_44100_128")
    body = {"text": text, "model_id": config.get("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
            # calm and even, not excitable
            "voice_settings": {"stability": 0.8, "similarity_boost": 0.75, "style": 0.0, "speed": 0.95}}
    req = urllib.request.Request(url, json.dumps(body).encode(), {
        "Content-Type": "application/json",
        "xi-api-key": config.get("ELEVENLABS_API_KEY", ""),
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def speak(text):
    """Speak on the laptop. Uses ElevenLabs if there is a key, else the Mac's own voice."""
    if not config.get("ELEVENLABS_API_KEY"):
        subprocess.run(["say", text])
        return
    try:
        mp3 = synthesize(text)
    except Exception as e:   # out of credits, network, ...: never go silent
        print(f"!!! ElevenLabs failed ({e}), using the Mac voice", flush=True)
        subprocess.run(["say", text])
        return
    with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
        f.write(mp3)
        f.flush()
        subprocess.run(["afplay", f.name])
