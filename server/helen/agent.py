"""Voice-agent demo mode (VOICE_AGENT=1 in .env).

Whoever talks near the band gets an answer from "Sri", an AI persona, spoken in the
ElevenLabs voice. Each sentence heard is also sent to the iPhone receiver app (its Mac
server, ios/receiver-app) so the phone vibrates it as Morse while the person speaks.
"""
import json
import urllib.request

from helen import config
from helen.expand import ask

IOS_SERVER = config.get("IOS_SERVER", "http://127.0.0.1:8770")   # the receiver app's Mac server

PERSONA = """You are Sri, a deafblind person at VexoHacks, an AI wearables hackathon at Y Combinator \
in San Francisco. You "talk" through Helen, a wristband: you tap, and an AI voice speaks for you. \
You are warm, curious and brief. Reply to what the other person just said with ONE short, \
natural spoken sentence (at most 15 words). Ask about their project now and then. Never use emoji \
or lists.

If what was heard is clearly not said to you (background chatter, a fragment, people talking \
to each other), reply with exactly: SKIP

Conversation so far:
{history}

They just said: {sentence}"""


def reply(sentence, history):
    """Sri's spoken answer, or None when the sentence was not meant for Sri."""
    answer = ask(PERSONA.format(sentence=sentence, history="\n".join(history[-8:]) or "(none)"))
    if not answer or answer.strip().upper().startswith("SKIP"):
        return None
    return answer.strip().strip('"')


def vibrate_on_phone(sentence):
    """Send what was heard to the iPhone receiver app's server; the app vibrates it."""
    body = json.dumps({"text": sentence, "compact": False}).encode()
    req = urllib.request.Request(IOS_SERVER + "/transcripts", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status
