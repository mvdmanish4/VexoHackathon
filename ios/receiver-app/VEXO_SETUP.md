# Vexo: complete setup and demo guide

This guide sets up the [Vexo Conversation repository](https://github.com/anupahuje/Vexo-Conversation) on a teammate’s Mac and iPhone. Start with a simulated sentence, then test a band tap, then try a live conversation.

**Incoming:** Vexo band microphone → Mac → Deepgram transcription → optional OpenAI shortening → iPhone Morse vibrations.

**Outgoing:** Vexo band taps → Mac decodes Morse → iPhone speaks the decoded text.

## 1. Get access and install the tools

- Accept the invitation to the private GitHub repo. If you see a 404 while signed in, ask the owner to add your GitHub username.
- On the Mac, install [uv](https://docs.astral.sh/uv/getting-started/installation/). It manages Python and the project dependencies.
- For physical iPhone vibrations and spoken replies, install [Xcode](https://developer.apple.com/xcode/). You’ll need an Apple Account, an iPhone that supports Core Haptics, and a data cable. You can do the Mac browser demo while Xcode downloads.
- Put the Mac and iPhone on the same trusted Wi-Fi network. Have the numbered Vexo band ready for the hardware tests.

## 2. Start the Mac demo

Open Terminal and run these lines one at a time:

```bash
git clone https://github.com/anupahuje/Vexo-Conversation.git
cd Vexo-Conversation
bash setup-demo.sh
```

The setup script downloads the pinned Vexo SDK and dependencies, creates a local `.env` file, and starts the receiver on port 8765. Keep this Terminal window open. It prints two values for your iPhone: **receiver address** and **receiver code**.

Open [localhost:8765](http://localhost:8765) on the Mac. Enter **Are you ready to go?** and click **Send simulated turn**. The sentence should appear in the transcript. This step does not need a band, iPhone, API keys, or Xcode.

## 3. Install and connect the iPhone app

1. In Finder, open the project’s `ios/VexoReceiver.xcodeproj`.
2. In Xcode, select the **VexoReceiver** target, open **Signing & Capabilities**, enable **Automatically manage signing**, and choose your own team. If there is no team, add your Apple Account in **Xcode → Settings → Accounts**. If the bundle identifier is already taken, change it to a unique one, such as `com.yourname.vexoconversation`.
3. Plug in and unlock your iPhone. Tap **Trust** if prompted. Select the physical iPhone in Xcode’s run destination menu, then click **Run**. If prompted, enable **Settings → Privacy & Security → Developer Mode** on the phone, restart it, and confirm Developer Mode after the restart. If the phone reports an untrusted developer, follow its prompt to trust the developer profile. See Apple’s guides to [running on a physical device](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices) and [Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device).
4. Open **Vexo** on the iPhone. Tap **Test Morse for S** and feel for three short pulses. Tap **Test iPhone speaker** to hear the letter “E.” These two buttons work before connecting to the Mac.
5. Open **Connection settings** in Vexo and enter the address and code printed by your Mac. Tap **Connect to Vexo**, allow local network access if asked, and wait for **Connected**. Keep the app in the foreground.
6. Send a fresh sentence in the Mac browser. The iPhone should show it and play the Morse automatically. Send a second sentence to check that it plays in order without tapping again. Adjust **Dot duration** if the pulses are hard to distinguish.

The iPhone starts with new messages, so always send a test sentence **after** it says **Connected**. The simulator can preview the interface; use the physical iPhone to feel the vibrations.

## 4. Test a reply from the band

This test does not need API keys. Keep the Mac receiver and the iPhone app running. In a second Terminal window, open the same project folder. Close any Vexo SDK dashboard that might already be using the band. Double-tap your band to make it discoverable, then run:

```bash
uv run --locked --extra band python band.py --tap-only --band 46
```

Replace `46` with the number on your band’s bag. Wait for the Mac to report that the band is connected. Tap the band **once**, then wait five seconds. The iPhone should show **Last band reply: E** and say “E.” Press **Control+C** in the band Terminal when ready to switch to live speech.

## 5. Enable live speech and optional shortening

In a Terminal window in the project folder, open the local settings file:

```bash
open -e .env
```

Paste the team’s Deepgram key after `DEEPGRAM_API_KEY=`. Deepgram is required for the band microphone test: the Vexo SDK supplies audio, and Deepgram converts it to text. To try shortening, paste an authorized OpenAI key after `OPENAI_API_KEY=`. The demo can send the original transcript even with that field blank. Leave `VEXO_RECEIVER_CODE=` and its generated value in place. Save the file. Keep these values in the Mac’s ignored `.env`; don’t paste them into chat, GitHub, or the iPhone app.

Stop the receiver with **Control+C** in its Terminal window and run `bash setup-demo.sh` again so it reloads the settings. Reconnect the iPhone if needed. In the second Terminal window, make the band discoverable again and run:

```bash
uv run --locked --extra band python band.py --live --band 46
```

Tell people nearby before pressing **Enter** to turn on the microphone. Band audio goes to Deepgram; with shortening enabled, finalized transcript text goes to OpenAI. To try live transcription without sending text to OpenAI, add `--verbatim` to the command. Press **Control+C** in the band Terminal to stop the microphone.

## 6. Run the full conversation test

1. With the iPhone connected, say **“Are you ready to go?”** near the band and pause. Look for the sentence in the iPhone transcript and feel its Morse pattern.
2. If Vexo chooses a shorter version, compare it with the original. Use **Replay full message** if the shorter version is hard to understand. If there’s no useful shortening, Vexo keeps the original.
3. Tap a reply on the band. A single tap is a dot; a quick double-tap is a dash. Within a letter, leave a short beat between symbols. Pause roughly **two seconds** between letters, **three seconds** between words, and **five seconds** after the last symbol to send. For the first round trip, send **E** with one tap.
4. Confirm that the iPhone displays and says the reply. Wait for it to finish speaking before starting the next turn. A successful test means you felt the incoming message and heard the physical band’s reply.

## Troubleshooting

| What you see | What to try |
| --- | --- |
| GitHub says the repo is missing | Confirm the invitation was accepted on the same GitHub account you use to clone. |
| Terminal says `uv: command not found` | Install uv using the link above, then reopen Terminal. |
| iPhone is stuck connecting | Keep the Mac receiver running. Confirm both devices are on the same network and Vexo has Local Network access. If the `.local` address fails, find the Mac’s Wi-Fi IP under **System Settings → Wi-Fi → Details → TCP/IP** and enter `http://<Mac-IP>:8765` in Vexo. Guest Wi-Fi can prevent devices from reaching each other. |
| Text arrives but there’s no vibration | Run **Test Morse for S** on the physical iPhone. Keep Vexo open, tap **Resume** if paused, and try increasing **Dot duration**. |
| Reply appears but the phone doesn’t speak | Tap **Test iPhone speaker**, turn up the volume, and check whether audio is routed to headphones. |
| The Mac can’t find the band | Check the printed number, turn on Mac Bluetooth, allow Bluetooth access if asked, and close competing Vexo SDK tools. Double-tap to make the band discoverable again. If using a supported USB connection, add `--usb`. |
| Taps work but live words don’t arrive | Make sure you started `--live` and pressed Enter, check the Deepgram key in `.env`, then try a short sentence and pause. Keep the simulated demo as a fallback if the venue network blocks Deepgram. |
