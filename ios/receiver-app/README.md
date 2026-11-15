# Vexo speech receiver

The [Vexo Open Kit](https://github.com/VexoAI-Org/vexo-open-kit) carries audio from the band's microphone to the Mac. Its Deepgram adapter emits finalized speech turns. OpenAI suggests shorter wording for each turn, then the receiver measures the actual Morse playback cost for each candidate. It keeps the original and uses a candidate only if it plays faster and passes checks for numerals, negation and question marks. Review the original or replay it at any time.

The browser previews the transcript and timing. The native iPhone app plays the same pattern through Core Haptics, with adjustable speed, pause and replay. A queue keeps each turn in order even when speech arrives faster than playback.

## Start on the Mac

On a Mac with [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, clone this repository, open Terminal in the project folder, and run:

```bash
bash setup-demo.sh
```

The script checks out the pinned Vexo SDK, installs the Python dependencies, and starts the receiver. Keep that Terminal window open. Go to http://localhost:8765 and click **Send simulated turn**. No band or API keys are needed for the simulated demo. The script also prints an address and receiver code for the iPhone. Alternatively, send a custom simulated transcript from a second Terminal window:

```bash
uv run --locked --extra band python band.py --sim --say "Are you ready to go?"
```

For OpenAI shortening, put your own `OPENAI_API_KEY` in the project's local `.env` and restart the receiver. The original still reaches the phone if OpenAI is unavailable or produces no usable savings. Add `--verbatim` to keep the full text on purpose.

## Try the iPhone

1. Install [Xcode](https://developer.apple.com/xcode/) and open `ios/VexoReceiver.xcodeproj`.
2. Plug in the iPhone, trust the Mac, and enable Developer Mode if prompted. In Xcode, select a signing team under **Signing & Capabilities**, then select your iPhone and press **Run**. If signing reports that the bundle identifier is taken, give the target a unique identifier. [Apple device setup](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices)
3. In the app, tap **Test Morse for S**. You should feel three short pulses. This test runs entirely on the phone.
4. Put the Mac and iPhone on the same trusted Wi-Fi. In Vexo, open **Connection settings** and enter the receiver address and code printed by the setup script.
5. Tap **Connect to Vexo**. Allow Local Network access if prompted. If the address ending in `.local` does not work, use the Mac’s Wi-Fi IP address instead (in **System Settings → Wi-Fi → Details → TCP/IP**).
6. Run the simulation again. Check the original wording, compact wording, and saved playback time. Use **Replay full message** to feel the original. Enter `http://127.0.0.1:8765` with a blank code when testing the UI in the iOS Simulator on the Mac.

The LAN demo uses HTTP on a trusted network. The pairing code protects access to the transcript feed. Keep the server on localhost for Mac-only tests.

The native receiver starts at the head of the feed on a fresh connection. Send a new turn after its status reads **Connected**. The app keeps the display awake while connected. **Test a band reply** shows the last decoded band reply and lets you test the speaker. Under **Reply on iPhone**, type an answer or enter Morse using **Dot**, **Dash**, **Add letter**, and **Space**. **Speak reply** reads it aloud and pauses haptics. Tap **Resume** to feel the queued messages.

## Preview on iPhone without Xcode

Copy `iphone_preview.py` to the iPhone using AirDrop or Files, then open the script in [Pyto IDE](https://apps.apple.com/us/app/pyto-ide/id1436650069) and press Run. Enter the same Mac address and receiver code as in the native instructions above. Allow Local Network access if prompted. Pyto plays three test pulses, then fetches and plays transcript turns in order while the script is running in the foreground. Use Pyto's Stop button to end playback. This preview has console output. The native receiver provides pause, speed changes during playback, and full-message replay controls.

For a file-only haptic test, open an Apple Haptic Audio Pattern file in [Haptiq](https://apps.apple.com/us/app/haptiq/id6748824254) using its AHAP import, then tap Play. This plays the exported pattern locally without a connection to the Mac.

## Connect a band

Add the team’s `DEEPGRAM_API_KEY` to the Mac's local `.env`. Close the SDK dashboard, double-tap your band, and run:

```bash
uv run --locked --extra band python band.py --live --band 46
```

Replace 46 with the number printed on your team's band bag. Add `--usb` for the USB connection. Tell people nearby before pressing Enter to enable the microphone. The kit sends audio to Deepgram, and the server sends finalized transcript text to OpenAI for shortening. Ctrl+C stops the microphone and flushes the last speech turn. The provider keys stay on the Mac.

When the iPhone is connected, tap once for a dot and double-tap for a dash. Pause at least 1.5 seconds between letters, at least 2.8 seconds between words, and 5 seconds after the last symbol to send the reply. The Mac pauses incoming microphone audio briefly while it collects and speaks the reply. Wait for the phone to finish speaking before the other person starts their next turn. For a quick reply test, run `uv run --locked --extra band python band.py --tap-only` and tap once to send **E**.
