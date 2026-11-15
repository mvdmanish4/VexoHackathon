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

PERSONA = """You are Shri, an Indian man who is deafblind, at VexoHacks, an AI wearables hackathon at \
Y Combinator in San Francisco. You feel what people say as vibrations on your phone and tap your \
replies; an AI voice speaks for you. You are calm, friendly and understated, never excited or gushing: \
no exclamation marks. Reply to what the other person just said with ONE short, natural spoken \
sentence (at most 15 words). Ask about their project now and then. Never use emoji, lists or \
stage directions.

If what was heard is clearly not said to you (background chatter, a fragment, people talking \
to each other), reply with exactly: SKIP

Conversation so far:
{history}

They just said: {sentence}"""


def reply(sentence, history, always=False):
    """Sri's spoken answer, or None when the sentence was not meant for Sri.
    always=True (they spoke into Sri's phone): it is for Sri, never skip."""
    prompt = PERSONA.format(sentence=sentence, history="\n".join(history[-8:]) or "(none)")
    if always:
        prompt = prompt.replace("If what was heard is clearly not said to you", "(Ignore this rule:")
    answer = ask(prompt)
    if not answer or answer.strip().upper().startswith("SKIP"):
        return None if not always else "Sorry, could you say that again?"
    answer = answer.strip().strip('"')
    for label in ("Me:", "Sri:", "Them:"):               # the model sometimes copies the history labels
        if answer.startswith(label):
            answer = answer[len(label):].strip()
    return answer


def vibrate_on_phone(sentence):
    """Send what was heard to the iPhone receiver app's server; the app vibrates it."""
    body = json.dumps({"text": sentence, "compact": False}).encode()
    req = urllib.request.Request(IOS_SERVER + "/transcripts", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status
