# TapTalk

**A voice for people who are deaf, blind and cannot speak, using only a wristband.**

The person taps Morse code on a Vexo band. The laptop decodes the taps, **Gemini** turns the
short tapped words into the sentence they mean, and **ElevenLabs** says it out loud in a
natural human voice, so the hearing people around them understand at once.

```
tap tap tap tap · tap tap · turn wrist over
        │
        ▼
Vexo band (motion sensor) ──Bluetooth──► laptop: Morse decoder ──► "HI"
                                                   │
                                     Gemini: "WTR PLS" → "Could I have some water, please?"
                                                   │
                                     ElevenLabs voice ──► spoken out loud
```

No screen, no sight and no hearing needed: every control is a touch gesture.

## The tap language

| Do this | Means |
|---|---|
| Tap once | dot `.` |
| Double tap | dash `-` |
| Short pause (starts at 1.2 s) | end of the letter (the laptop softly says the letter) |
| Longer pause (starts at 2.6 s) | space between words |
| Six or more single taps in one letter | delete the last letter |
| Turn the wrist over (palm up) | **send**: the message is spoken |
| Stay still (starts at 6 s) | send (fallback) |

**The pauses adapt to the person.** After a few letters TapTalk measures how fast they tap
and sets the letter pause to 3× their usual gap between taps (0.6–2.0 s), the word pause to
2.2× that, and the auto-send to 4× (at least 4 s). A practised tapper ends up around
0.8 s per letter. `--fixed` turns this off.

Morse cheat sheet:

```
A .-    B -...  C -.-.  D -..   E .     F ..-.  G --.   H ....  I ..
J .---  K -.-   L .-..  M --    N -.    O ---   P .--.  Q --.-  R .-.
S ...   T -     U ..-   V ...-  W .--   X -..-  Y -.--  Z --..
```

Short words work well because Gemini expands them: `WTR` (water), `PLS` (please),
`THX` (thanks), `HLP` (help).

## Run it

Python 3.9+ on a Mac (it speaks with `afplay` / `say`).

```bash
git clone https://github.com/VexoAI-Org/vexo-open-kit.git   # the kit, inside this folder
python3 -m pip install bleak certifi
python3 -m unittest discover -s tests          # decoder tests, no band needed
python3 taptalk.py --band N --sim              # pretend band taps "HELP ME" and sends it
python3 taptalk.py --band N --sim --demo "WTR PLS"   # tap an abbreviation: Gemini expands it
python3 taptalk.py --band N                    # your real band (double-tap it first)
```

`N` is the number printed on your band's bag (band 7 is `Vexo-HACK-07`). The program only
ever connects to that one band.

Options: `--debug` prints every raw band event and the time from send to sound. `--no-ai` speaks the letters as tapped.
`--no-eleven` uses the Mac voice. `--letter-gap`, `--word-gap` and `--send-gap` change the
starting pauses. `--fixed` keeps them fixed. `--no-speculate` turns off preparing the voice
while tapping. `--tap-threshold` sets tap strength in g. `--send-face` sets the side that means
"send". `--dedup` is explained below.

## Sponsor keys (optional)

Copy `env.example` to `.env` and fill it in yourself (`.env` is git-ignored), or `export` the
variables in your terminal. Never commit a key or paste it into a chat.

| Variable | Used for | Without it |
|---|---|---|
| `GEMINI_API_KEY` | Gemini expands short taps into a sentence. It uses **Gemini 4** when the key has it (`gemini-4-hydrogen`, the fastest at about 2 s, then `argon`, then `carbon`), else the newest Gemini flash model. It works out each model's fastest thinking setting by itself. Set `GEMINI_MODEL` to force a model | The tapped letters are spoken as they are |
| `ELEVENLABS_API_KEY` | ElevenLabs speaks the message (`ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL` to change the voice and model) | The Mac's built-in voice speaks |

Letters and "deleted" cues always use the instant local voice, so feedback is never delayed.
If a service fails or is unreachable, TapTalk prints the status number and carries on with
the fallback.

## Why it is fast

- **Sound plays inside the program.** Starting `say` or `afplay` took 1.7–3.9 s per sound on
  our Mac. TapTalk keeps one macOS speech engine open (PyObjC), so a sound starts in about
  20 ms. Send to sound measured 3,163 ms before this and 35 ms after (Mac voice, pretend band).
- **Real words skip the AI.** If every tapped word is in the dictionary (`HELP ME`), it is
  spoken at once. Only abbreviations like `WTR PLS` go to Gemini, which answers with
  thinking turned off.
- **The voice is ready before you send.** At every word break, Gemini and ElevenLabs start
  on the text so far. Most people pause before turning the wrist, so the audio is usually
  ready when they send.
- **The message never waits.** A letter cue still being spoken is cut off, and queued cues
  are skipped, the moment a message is ready.
- If the ElevenLabs key is refused, TapTalk stops asking for the rest of the session.

## First time with the real band: tune it

1. Run `python3 taptalk.py --band N --debug`.
2. **Double tap once.** If you see `tap` and then `double-tap`, the band sends an extra tap
   for every double tap: run with `--dedup 0.3`.
3. **Turn your wrist over.** Note the `face=` shown when your palm faces up. If it is not
   `-z`, pass it as `--send-face`.
4. If light taps are missed, lower `--tap-threshold` (for example 0.6). If arm movements count
   as taps, raise it.
5. Blindfold test: a teammate taps `... --- ...` with eyes closed, turns the wrist over, and
   the laptop says "SOS".

## Lookout: the phone warns of a wall ahead

A second helper for the same person. The phone's camera looks ahead and the phone vibrates
when something is in the way. No app: the laptop serves a web page.

```bash
python3 lookout.py        # prints an https:// address; open it on the phone (same Wi-Fi)
```

1. The first time, the phone warns about the certificate (a camera page needs HTTPS and the
   laptop makes its own certificate): **Show details → visit this website**.
2. Press **Start** and allow the camera. Hold the phone at chest height, camera forward.
3. About once a second a small photo goes to the laptop and **Gemini** says what is ahead.

| Gemini says | The phone | The screen |
|---|---|---|
| `stop`: about 1 m or closer | fast ticks that do not stop | red |
| `near`: about 1 to 3 m | two slow ticks | amber |
| `clear` | nothing | green |
| no answer | nothing | grey `?` (never shown as clear) |

On `stop` the laptop also says it out loud once ("Wall ahead"), so people nearby know why
the person stopped (`--quiet` turns that off). It needs `GEMINI_API_KEY` (see above).
iPhone ticks need iOS 18 or newer; Android uses the normal vibration.

Limits: Gemini judges distance from one photo, so it is a rough guess, and each look takes
1.5–3 s. It is a demo for slow walking, not a safety device.

## Files

- `morse.py`: the tap decoder (pure logic, unit-tested)
- `sponsors.py`: Gemini and ElevenLabs, each with an offline fallback
- `taptalk.py`: connects to the band, turns events into dots and dashes, speaks messages
- `lookout.py`: the camera wall warning (web page for the phone + Gemini)
- `tests/test_morse.py`: decoder tests
- `vexo-open-kit/`: the official kit, unchanged (git-ignored; clone it here)

## Next

Receiving: a hearing person speaks, Deepgram writes it down, and the words come back to the
user as Morse vibrations they can feel. The band has no vibration motor, so this needs a
small haptic add-on.

Lookout with real distance: an iPhone Pro's LiDAR sensor measures the distance to a wall
instantly and offline, but only from a native app, not a web page.
