# Helen: iPhone side

Two ways to get the deafblind person's phone involved:

| Folder | What it is | Needs |
|---|---|---|
| [`web/`](web/) | The phone page served by `server/` (port 8765, or the public ngrok link). Shows the conversation and live logs, vibrates Morse (iPhone ticks / Android vibration), flashes on screen. | Nothing to install: open it in Safari |
| [`receiver-app/`](receiver-app/) | Native SwiftUI iPhone app "VexoReceiver" (Core Haptics Morse, spoken replies, typed replies) with its own small Mac server. Imported from [anupahuje/Vexo-Conversation](https://github.com/anupahuje/Vexo-Conversation). See its README / VEXO_SETUP.md. | Xcode to build onto an iPhone |

Note: `receiver-app` polls its own server's `/transcripts` endpoint; `server/` does not serve that yet.
