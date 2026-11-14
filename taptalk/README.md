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
| Double tap (two quick taps) | dash `-` |
| Short pause (starts at 1.2 s) | end of the letter (the laptop softly says the letter) |
| Longer pause (starts at 2.6 s) | space between words |
| Six or more single taps in one letter | delete the last letter |
| Turn the wrist over and hold it for half a second | **send**: the message is spoken |
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

## How taps are found

The band has its own tap and double-tap detection, but its double-tap timing is fixed in the
firmware and on real bands it often reports one double tap as two single taps. That turned
dashes into dots and mixed up letters. So TapTalk reads the raw accelerometer instead, 833
times a second, and finds the taps itself:

- **A tap** is a sharp jolt that rises above `--tap-g` (default 1 g) over the slow average
  and is gone within 50 ms. Arm swings and wrist turns are slow, so they are never taps, and
  the ringing after a tap is ignored for 80 ms so one tap never counts twice.
- **A dash** is two taps closer together than `--double-window` (default 0.30 s). A tap with
  no partner in that time is a dot. `--calibrate` measures your own rhythm and sets it.
- **Send** is the wrist turned more than 70 degrees away from where it rests while tapping,
  held for half a second. It works however the band is worn: the resting direction is learnt
  at every tap. A tap made by the start of the turn is dropped.

`--detector band` goes back to the band's own events (and the `--send-face` orientation).

## Run it

Python 3.9+ on a Mac (it speaks with `afplay` / `say`).

```bash
git clone https://github.com/VexoAI-Org/vexo-open-kit.git   # the kit, inside this folder
python3 -m pip install bleak certifi
python3 -m unittest discover -s tests          # decoder tests, no band needed
python3 taptalk.py --band N --sim              # pretend band taps "HELP ME" and sends it
python3 taptalk.py --band N --sim --demo "WTR PLS"   # tap an abbreviation: Gemini expands it
python3 taptalk.py --band N --sim --detector raw   # the same, played as raw accelerometer taps
python3 taptalk.py --band N --calibrate        # real band, first time: learns your tap rhythm
python3 taptalk.py --band N                    # your real band (double-tap it first)
```

`N` is the number printed on your band's bag (band 7 is `Vexo-HACK-07`). The program only
ever connects to that one band.

Options: `--debug` prints every tap (strength and gap), what it became, movements that were
not taps, and the time from send to sound. `--double-window` and `--tap-g` set the tap
detector (use the numbers `--calibrate` prints). `--no-ai` speaks the letters as tapped.
`--no-eleven` uses the Mac voice. `--letter-gap`, `--word-gap` and `--send-gap` change the
starting pauses. `--fixed` keeps them fixed. `--no-speculate` turns off preparing the voice
while tapping. `--detector band` uses the band's own tap events; with it, `--tap-threshold`, `--send-face`
(default `+z`) and `--dedup` apply.

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

1. Run `python3 taptalk.py --band N --calibrate`. The laptop asks for five single taps, then
   five double taps, and prints the command to use, for example
   `python3 taptalk.py --band N --double-window 0.32 --tap-g 0.9`.
2. Run that command with `--debug`. Every tap prints its strength and the gap to the one
   before, then `-> dot` or `-> dash`.
   - Taps missed: lower `--tap-g` (for example 0.6).
   - Arm moves count as taps: raise `--tap-g`.
   - A double tap comes out as two dots: raise `--double-window` a little.
   - Two dots come out as a dash: lower it, or tap dots a little slower.
3. Turn the wrist over and hold it: `--debug` prints `send`.
4. Blindfold test: a teammate taps `... --- ...` with eyes closed, turns the wrist over, and
   the laptop says "SOS".

## Files

- `taps.py`: finds taps, dashes and the send turn in the raw accelerometer (pure logic, unit-tested)
- `morse.py`: the Morse decoder (pure logic, unit-tested)
- `sponsors.py`: Gemini and ElevenLabs, each with an offline fallback
- `taptalk.py`: connects to the band, turns events into dots and dashes, speaks messages
- `tests/`: decoder and tap detector tests
- `vexo-open-kit/`: the official kit, unchanged (git-ignored; clone it here)

## Next

Receiving: a hearing person speaks, Deepgram writes it down, and the words come back to the
user as Morse vibrations they can feel. The band has no vibration motor, so this needs a
small haptic add-on.
