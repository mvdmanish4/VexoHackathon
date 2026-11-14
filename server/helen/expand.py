"""AI step: turns short, possibly mistyped Morse words into one natural spoken sentence."""
import json
import urllib.request

from helen import config

# One-letter shortcuts: hard to mistype, instant to say.
QUICK = {
    "Y": "Yes.",
    "N": "No.",
    "T": "Thank you.",
    "R": "Sorry, could you please repeat that?",
    "H": "Hello! I'm deafblind, and I'm using this band to talk with you.",
}

PROMPT = """You are the voice of a deafblind, non-speaking person. They tap Morse code on a \
wristband, which is slow and error-prone, so they send only key words, often with typos \
(a dot misread as a dash, letters merged or dropped). Turn their words into ONE short, natural \
sentence that they would say out loud, in first person.

Rules:
- Fix likely Morse typos (e.g. "WATR" -> water, "HELO" -> hello).
- Never add facts, names, numbers or requests they did not tap.
- Keep it short and friendly. Output only the sentence, nothing else.
- If the words make no sense at all, output: Sorry, let me try that again.

Recent conversation (may be empty):
{history}

Tapped words: {words}"""


def expand(words, history=""):
    words = words.strip().upper()
    if words in QUICK:
        return QUICK[words]
    prompt = PROMPT.format(words=words, history=history or "(none)")
    if config.get("GEMINI_API_KEY"):
        return _gemini(prompt)
    if config.get("OPENAI_API_KEY"):
        return _openai(prompt)
    return words.capitalize() + "."   # no AI key: say the words as they are


def _post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _gemini(prompt):
    model = config.get("GEMINI_MODEL", "gemini-flash-latest")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _post(url, {"contents": [{"parts": [{"text": prompt}]}]},
                 {"x-goog-api-key": config.get("GEMINI_API_KEY")})
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _openai(prompt):
    data = _post("https://api.openai.com/v1/chat/completions",
                 {"model": config.get("OPENAI_MODEL", "gpt-4o-mini"),
                  "messages": [{"role": "user", "content": prompt}]},
                 {"Authorization": "Bearer " + config.get("OPENAI_API_KEY")})
    return data["choices"][0]["message"]["content"].strip()
