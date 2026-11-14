# Helen server

Runs on the laptop. Connects to the Vexo band over Bluetooth and does the thinking.

```sh
./setup.sh                                  # once: Vexo kit + Python env + .env
.venv/bin/python -m helen.main 46           # run with your band number
.venv/bin/python -m helen.main --sim        # pretend band
.venv/bin/python -m unittest discover tests # decoder tests, no band needed
```

## Tap language

| Do this | Means |
|---|---|
| Tap once | dot `.` |
| Double-tap | dash `-` |
| Pause (starts at 2 s, adapts to your speed) | end of letter |
| Longer pause (starts at 4.5 s) | end of word |
| 6+ single taps in one letter | delete the last letter |
| Turn the wrist over and hold 2 s | **send**: the message is spoken |

Quick phrases by counting taps (any speed), then send: 1 yes, 2 no, 3 thank you, 4 hello +
introduction, 5 please repeat. Also `Y` yes, `N` no, `TY` thank you, `R` repeat,
`H` hello + introduction.

## Files

| File | Job |
|---|---|
| `helen/main.py` | The server: taps in, voice out |
| `helen/band.py` | Connect to the band, retry, auto-reconnect |
| `helen/taps.py` | Band gestures to Morse symbols, send gesture |
| `helen/morse.py` | Morse decoder with adaptive pauses and delete (pure logic, tested) |
| `helen/expand.py` | AI: short tapped words to a natural sentence (OpenAI, falls back to Gemini 4) |
| `helen/voice.py` | ElevenLabs voice, falls back to the Mac voice |
| `helen/config.py` | Reads keys from `.env` |
| `tools/` | Debug helpers: `tap_probe` (raw events), `tap_to_text` (decode without speaking) |
| `tests/` | Decoder tests |

Keys go in `.env` (see `.env.example`), never in git.
