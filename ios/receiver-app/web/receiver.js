const pause = document.querySelector("#pause");
const speed = document.querySelector("#speed");
const listeningStatus = document.querySelector("#listening-status");
const playbackStatus = document.querySelector("#playback-status");
const history = document.querySelector("#history");

class Playback {
  queue = [];
  active = null;
  timer = null;
  paused = false;
  supported = typeof navigator.vibrate === "function";

  add(message, replay = false) {
    if (!message.steps.length) return;
    const job = { steps: message.steps, index: 0 };
    if (replay) {
      this.interrupt();
      if (this.active) this.queue.unshift(this.active);
      this.active = job;
    } else {
      this.queue.push(job);
    }
    this.advance();
  }

  interrupt() {
    if (this.timer === null) return;
    clearTimeout(this.timer);
    this.timer = null;
    navigator.vibrate?.(0);
  }

  advance() {
    const pending = this.queue.length + Number(this.active !== null);
    if (this.timer !== null) return;
    if (this.paused || document.hidden) {
      playbackStatus.textContent = `Vibrations paused. ${pending} segments queued.`;
      return;
    }
    this.active ??= this.queue.shift() ?? null;
    if (!this.active) {
      playbackStatus.textContent = "Vibration queue is empty.";
      return;
    }

    const { steps, index } = this.active;
    const { pattern, gap } = steps[index];
    const unit = Number(speed.value);
    if (this.supported && !navigator.vibrate(pattern.map(length => length * unit))) {
      playbackStatus.textContent = "Vibration was blocked. Tap Resume playback to retry.";
      this.paused = true;
      updatePauseButton();
      return;
    }
    playbackStatus.textContent = `${this.supported ? "Playing" : "Previewing"} Morse. ${this.queue.length} turns waiting.`;
    const interval = pattern.reduce((sum, length) => sum + length, 0) + (gap || 7);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.active.index += 1;
      if (this.active.index === steps.length) this.active = null;
      this.advance();
    }, interval * unit);
  }
}

const playback = new Playback();
function updatePauseButton() {
  pause.textContent = playback.paused ? "Resume playback" : "Pause playback";
  pause.setAttribute("aria-pressed", String(playback.paused));
}

pause.addEventListener("click", () => {
  playback.paused = !playback.paused;
  playback.interrupt();
  updatePauseButton();
  playback.advance();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) playback.interrupt();
  playback.advance();
});
speed.addEventListener("input", () => {
  document.querySelector("#speed-value").textContent = `${speed.value} ms`;
});

function addTurn(turn) {
  document.querySelector("#empty").hidden = true;
  const entry = document.createElement("li");
  const original = document.createElement("p");
  const selected = document.createElement("p");
  const morse = document.createElement("code");
  const timing = document.createElement("p");
  original.textContent = `Original: ${turn.original.text}`;
  selected.textContent = `Playing: ${turn.selected.text}`;
  morse.textContent = turn.selected.morse;
  const saved = Math.round(100 * (1 - turn.selected_units / Math.max(1, turn.original_units)));
  timing.textContent = turn.status === "compacted"
    ? `${saved}% shorter Morse playback · OpenAI ${turn.openai_ms} ms`
    : turn.status.startsWith("openai_") || turn.status === "no_key"
      ? "Compaction unavailable. Playing the original."
      : "Playing the original.";
  entry.append(original, selected, morse, timing);
  for (const [label, message] of [["Replay", turn.selected], ["Replay full message", turn.original]]) {
    if (label === "Replay full message" && turn.status !== "compacted") continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = label;
    button.addEventListener("click", () => playback.add(message, true));
    entry.append(button);
  }
  history.prepend(entry);
  playback.add(turn.selected);
}

let feedSession = "";
let after = 0;
async function poll() {
  try {
    const query = new URLSearchParams({ after, session: feedSession });
    const response = await fetch(`/transcripts?${query}`, { cache: "no-store" });
    if (!response.ok) throw new Error();
    const feed = await response.json();
    if (feed.session !== feedSession) {
      after = 0;
      feedSession = feed.session;
    }
    for (const turn of feed.messages) {
      if (turn.kind !== "reply") addTurn(turn);
      after = turn.id;
    }
    listeningStatus.textContent = feed.missed
      ? "Older turns have left the server’s history."
      : "Connected to the transcript feed.";
  } catch {
    listeningStatus.textContent = "Transcript feed unavailable. Retrying…";
  } finally {
    setTimeout(poll, 450);
  }
}

document.querySelector("#demo").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#send");
  button.disabled = true;
  try {
    const response = await fetch("/transcripts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: document.querySelector("#demo-text").value }),
    });
    if (!response.ok) throw new Error();
  } catch {
    playbackStatus.textContent = "Could not send the simulated turn.";
  } finally {
    button.disabled = false;
  }
});

void poll();
