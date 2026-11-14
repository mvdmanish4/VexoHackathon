# Helen

**A wristband that lets deafblind and non-speaking people talk with anyone.**

Built at VexoHacks (Y Combinator, Nov 14 2026) on the Vexo Open band.

## How it works

```
Deafblind person taps Morse ──▶ Band ──▶ Laptop (server) ──▶ iPhone ──▶ 🔊 spoken sentence
Other person speaks ──────────▶ Band ──▶ Laptop (server) ──▶ iPhone ──▶ 📳 Morse vibration
```

- **Taps → speech:** single tap = dot, double-tap = dash. The server decodes Morse, an AI turns
  short words into a natural sentence (`WATER PLS` → "Could I have some water, please?"), and
  ElevenLabs speaks it.
- **Speech → touch:** the band's mic feeds Deepgram, an AI shortens the sentence to key words,
  and the iPhone vibrates them as Morse.

## Repo layout

| Folder | What it is |
|---|---|
| [`server/`](server/) | Python app on the laptop: talks to the band over Bluetooth, runs Morse, AI and voice |
| [`ios/`](ios/) | iPhone app: plays the voice and vibrates Morse |

## Quick start (server)

```sh
cd server
./setup.sh                                  # clones the Vexo kit, makes a Python env
.venv/bin/python -m tools.tap_probe --sim   # pretend band, no hardware needed
.venv/bin/python -m tools.tap_probe 42      # your real band number
```
