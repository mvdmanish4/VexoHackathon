"""AI step: turns short, possibly mistyped Morse words into one natural spoken sentence."""
import json
import urllib.error
import urllib.request

from helen import config
from helen.morse import MORSE

MORSE_CODE = {letter: code for code, letter in MORSE.items()}

# Shortcuts by counting taps, at any speed (a quick pair that decoded as a dash counts as 2).
# Used for very short messages (up to 3 letters, 5 taps in total), however the pauses fell.
QUICK_COUNT = {
    1: "Yes.",
    2: "No.",
    3: "Thank you.",
    4: "Hello! I'm deafblind, and I'm using this band to talk with you.",
    5: "Sorry, could you please repeat that?",
}


def tap_count(letter):
    """How many taps a single letter took: a dot is 1 tap, a dash (quick pair) is 2."""
    code = MORSE_CODE.get(letter.upper())
    return sum(1 if s == "." else 2 for s in code) if code else None


def quick(words):
    """The quick phrase for a very short tapped message (counted in taps), or None."""
    letters = words.replace(" ", "").strip()
    if not 1 <= len(letters) <= 3:
        return None
    counts = [tap_count(c) for c in letters]
    if None in counts:
        return None
    return QUICK_COUNT.get(sum(counts))


PROMPT = """You are the voice of a deafblind, non-speaking person. They tap Morse code on a \
wristband, which is slow and error-prone, so they send only key words, often with typos \
(a dot misread as a dash, letters merged or dropped). Turn their words into ONE short, natural \
sentence that they would say out loud, in first person.

Rules:
- Fix likely Morse typos and expand abbreviations (WTR = water, PLS = please, THX = thanks,
  HLP = help, "COFE" = coffee).
- A bare noun is usually a polite request for that thing.
- Never add facts, names, numbers or requests they did not tap.
- Keep it short and friendly. Output only the sentence, nothing else.
- If the words make no sense at all, output: Sorry, let me try that again.

Examples:
COFE -> Could I get a coffee, please?
WTR PLS -> Could I have some water, please?
HLP -> I need help, please.
BATHRM -> Where is the bathroom, please?
NAME -> What is your name?

Recent conversation (may be empty):
{history}

Tapped words: {words}"""


def expand(words, history=""):
    words = words.strip().upper()
    if quick(words):
        return quick(words)
    answer = ask(PROMPT.format(words=words, history=history or "(none)"))
    return answer or words.capitalize() + "."   # no AI available: say the words as they are


_refused = set()   # services that refused the key (no credits, bad key): skip for this run


def ask(prompt):
    """Answer from the first AI that works (OpenAI, then Gemini), or None if none does."""
    for key, service in (("OPENAI_API_KEY", _openai), ("GEMINI_API_KEY", _gemini)):
        if config.get(key) and key not in _refused:
            try:
                return service(prompt)
            except Exception as e:   # out of credits, network, ...: try the next service
                if getattr(e, "code", None) in (401, 402, 403):
                    _refused.add(key)
                print(f"!!! {key.split('_')[0]} failed ({e}), trying the next AI", flush=True)
    return None


def _post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


# Gemini 4 first (the sponsor track), fastest first as measured on 2026-11-14:
# hydrogen ~2.2 s, argon ~3.7 s, carbon ~4.9 s per answer. Then the newest flash model.
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_PREFERENCE = ["gemini-4-hydrogen", "gemini-4-argon", "gemini-4-carbon"]

# Ways to ask a model to answer without long thinking, tried in order until one works.
# Older models take thinkingBudget 0; Gemini 4 refuses that or ignores it and wants a level.
THINKING_STYLES = [
    {"maxOutputTokens": 60, "thinkingConfig": {"thinkingBudget": 0}},
    {"maxOutputTokens": 600, "thinkingConfig": {"thinkingLevel": "low"}},
    {"maxOutputTokens": 600},
]
_gemini_state = {"model": None, "style": 0}


def _gemini_model():
    """GEMINI_MODEL if set, else a Gemini 4 model if the key has one, else the newest flash."""
    if _gemini_state["model"]:
        return _gemini_state["model"]
    model = config.get("GEMINI_MODEL")
    if not model:
        req = urllib.request.Request(GEMINI_BASE + "/models?pageSize=200",
                                     headers={"x-goog-api-key": config.get("GEMINI_API_KEY")})
        with urllib.request.urlopen(req, timeout=10) as r:
            names = [m["name"].split("/", 1)[-1] for m in json.load(r).get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
        model = next((m for m in GEMINI_PREFERENCE if m in names), None)
        if not model:
            flash = [n for n in names if n.startswith("gemini-") and "flash" in n
                     and not any(w in n for w in ("image", "tts", "live", "audio"))]
            model = max(flash, key=_flash_rank) if flash else "gemini-flash-latest"
    _gemini_state["model"] = model
    return model


def _flash_rank(name):
    try:
        version = tuple(int(p) for p in name.split("-")[1].split("."))
    except ValueError:
        version = (0,)
    return version, "preview" not in name and "exp" not in name


def _gemini(prompt):
    model = _gemini_model()
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    for style in range(_gemini_state["style"], len(THINKING_STYLES)):
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, **THINKING_STYLES[style]}}
        try:
            candidate = _post(url, body, {"x-goog-api-key": config.get("GEMINI_API_KEY")})["candidates"][0]
        except urllib.error.HTTPError as e:
            if e.code == 400:   # this model does not take that setting: ask the next way
                continue
            raise
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip().strip('"')
        if text:
            _gemini_state["style"] = style   # remember what works for the next message
            return text
    raise RuntimeError(f"Gemini ({model}) gave no answer")


def _openai(prompt):
    data = _post("https://api.openai.com/v1/chat/completions",
                 {"model": config.get("OPENAI_MODEL", "gpt-4o-mini"),
                  "messages": [{"role": "user", "content": prompt}]},
                 {"Authorization": "Bearer " + config.get("OPENAI_API_KEY")})
    return data["choices"][0]["message"]["content"].strip()
