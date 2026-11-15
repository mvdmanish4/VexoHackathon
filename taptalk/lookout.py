"""Lookout: the phone's camera warns a deaf-blind person of anything dangerous ahead, by touch
(a wall, stairs, a drop, a road with cars, a person, fire, a wet floor, ...).

The laptop serves one web page. The phone opens it, its rear camera sends a small photo
about once a second, Gemini says whether something is in the way, and the phone vibrates:

    stop  (within about 1 m, or a serious danger such as stairs down, a road or fire)
                                  three fast ticks, then the obstacle spelled in Morse
                                  (WALL = .-- .- .-.. .-..), then three fast ticks repeating
    near  (about 1 to 3 m)        N in Morse (-.), then one slow tick repeating
    clear                         nothing

Morse is felt the same way as in Helen: a dot is one tick, a dash is two quick ticks.

The laptop also says "Wall ahead" out loud once, so people nearby know why the person stopped.

    python3 lookout.py            then open the printed https:// address on the phone

To present it from Chrome on the laptop, open https://localhost:8766 : it uses the laptop's
camera. A laptop cannot vibrate, so each tick is a low buzz from the speakers and a shake of
the screen (and a rumble on a connected game controller).

Needs GEMINI_API_KEY in the environment or in ./.env (never printed or stored). A camera in a
web page needs HTTPS, so this makes a throwaway certificate; the phone shows one warning the
first time (Show details -> visit this website). Limits: Gemini judges distance from one
photo, so it is a rough guess, and each look takes 1.5-3 s. It is a demo for slow walking,
not a safety device.
"""
import argparse
import base64
import json
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sponsors import GEMINI_BASE, THINKING_STYLES, Gemini, Voice, _request

LOOK_INSTRUCTIONS = (
    "This photo is the view straight ahead of a deaf-blind person who is walking slowly, "
    "taken from a phone held at chest height. They cannot see or hear, so you are their only "
    "warning. Look for ANYTHING that could hurt them or that they could walk into, not only "
    "walls: stairs or a step up or down, a drop, kerb or platform edge, a hole, a road with "
    "cars, bikes or scooters, a person, an animal, a door (open or closed), glass, furniture, "
    "a pole, a low branch or sign at head height, a cable or object on the floor, a wet or "
    "icy floor, fire, a hot stove, a knife or other sharp thing, water, machinery. "
    "Answer with JSON only: "
    '{"level": "stop" | "near" | "clear", "what": "<ONE short word for the main danger>"}. '
    '"stop" = it is within about 1 metre or fills most of the view, OR it is a serious danger '
    "at any distance in their path (stairs down, a drop or edge, a road with moving vehicles, "
    "fire, a hole, water). "
    '"near" = something in their path about 1 to 3 metres ahead that is not yet serious. '
    '"clear" = nothing in the path for 3 metres or more (then "what" is ""). '
    'Use plain words such as wall, door, person, stairs, step, drop, edge, car, bike, chair, '
    'table, pole, glass, hole, cable, wet, fire, knife, water, dog. If two dangers show, name '
    "the worse one. If the photo is too dark or blurred to tell, answer stop with what = unclear."
)
LEVELS = ("stop", "near", "clear")
ALWAYS_STOP = {"stairs", "stair", "step", "steps", "drop", "edge", "kerb", "curb", "hole", "car",
               "truck", "bus", "bike", "scooter", "road", "traffic", "fire", "stove", "knife",
               "water", "pool", "train", "platform"}
_style = {"index": 0}       # the THINKING_STYLES entry that works for this model, remembered


def look(gemini, jpeg):
    """Ask Gemini what is ahead. Returns {"level", "what"}; level is "unknown" on any failure
    (never "clear": a failed look must not read as a free path)."""
    unknown = {"level": "unknown", "what": gemini.problem or "no answer"}
    if not gemini.ready:
        return unknown
    style = _style["index"]
    while style < len(THINKING_STYLES):
        config = {"temperature": 0, "responseMimeType": "application/json", **THINKING_STYLES[style]}
        body = {
            "systemInstruction": {"parts": [{"text": LOOK_INSTRUCTIONS}]},
            "contents": [{"role": "user", "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(jpeg).decode()}},
                {"text": "What is ahead?"}]}],
            "generationConfig": config,
        }
        try:
            with _request("%s/models/%s:generateContent" % (GEMINI_BASE, gemini.model), body,
                          {"x-goog-api-key": gemini.key}, timeout=8) as r:
                candidate = json.load(r)["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if text:
                _style["index"] = style
                answer = json.loads(text[text.index("{"):text.rindex("}") + 1])
                level = str(answer.get("level", "")).lower()
                if level not in LEVELS:
                    return unknown
                what = str(answer.get("what", ""))[:30]
                if level == "near" and what.lower() in ALWAYS_STOP:
                    level = "stop"          # serious dangers never get the softer warning
                return {"level": level, "what": what}
            if candidate.get("finishReason") != "MAX_TOKENS":
                return unknown
        except urllib.error.HTTPError as e:
            if e.code != 400:
                return {"level": "unknown", "what": "Gemini status %d" % e.code}
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
            return {"level": "unknown", "what": "Gemini not reachable"}
        style += 1
    return unknown


def send_to_receiver(url, code, word):
    """Hand the warning to the team's iPhone receiver app (ios/receiver-app), which plays it
    as Morse through the iPhone's real haptics engine (Core Haptics). Returns True if taken."""
    req = urllib.request.Request(
        url.rstrip("/") + "/transcripts", method="POST",
        data=json.dumps({"text": word, "compact": False}).encode(),
        headers={"Content-Type": "application/json", "X-Vexo-Code": code or ""})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Lookout</title>
<style>
  html, body { margin: 0; height: 100%; font-family: -apple-system, system-ui, sans-serif; }
  body { background: #222; color: #fff; display: flex; flex-direction: column;
         align-items: center; justify-content: center; text-align: center; transition: background .15s; }
  @keyframes shake { 0%,100% { transform: translate(0,0); } 20% { transform: translate(-9px,3px); }
    40% { transform: translate(8px,-3px); } 60% { transform: translate(-6px,2px); } 80% { transform: translate(5px,-2px); } }
  body.shake > * { animation: shake .11s linear; }
  body.stop { background: #c41616; } body.near { background: #c98a00; }
  body.clear { background: #14803c; } body.unknown { background: #444; }
  #word { font-size: 22vw; font-weight: 800; line-height: 1; text-transform: uppercase; }
  #what { font-size: 8vw; min-height: 1.3em; margin-top: .2em; }
  #morse { font-size: 9vw; min-height: 1.3em; font-family: ui-monospace, Menlo, monospace; letter-spacing: .1em; }
  #info { font-size: 4vw; opacity: .8; margin-top: 1em; padding: 0 1em; }
  button { font-size: 9vw; padding: .6em 1.2em; border: 0; border-radius: .4em; background: #fff; color: #111; }
  video { position: fixed; right: 8px; bottom: 8px; width: 28vw; border-radius: 8px; opacity: .85; }
</style></head><body class="unknown">
<button id="start">Start</button>
<button id="test" hidden style="position:fixed;left:8px;bottom:8px;font-size:4vw;padding:.5em .8em;opacity:.85">Test buzz</button>
<div id="word" hidden></div><div id="what"></div><div id="morse"></div><div id="info"></div>
<video id="cam" playsinline muted hidden></video>
<script>
// Haptics: iPhone (iOS 18+) ticks when a hidden "switch" is flipped; Android uses vibrate.
const canVibrate = typeof navigator.vibrate === "function";
// A laptop cannot vibrate. In a desktop browser (or with ?sound=1) every tick is a low
// motor-like buzz from the speakers plus a shake of the whole screen, so the audience
// hears and sees exactly what the phone would feel. A connected game controller rumbles too.
const desktop = !canVibrate && !("ontouchstart" in window);
// iPhone: a web page cannot always drive the Taptic Engine, so every pulse ALSO plays a loud
// low tone. At full volume the phone's own speaker shakes the case enough to feel in the hand.
const wantSound = desktop || new URLSearchParams(location.search).has("sound");
const phoneTone = !desktop && !canVibrate && wantSound;
// iPhone: the Taptic Engine is silenced while the camera is capturing (the same page with no
// camera vibrates fine). So on an iPhone the camera is closed after each photo, the warning
// is felt with the camera off, and the camera is opened again for the next look.
const iphone = !desktop && !canVibrate;
let audio = null;
function buzz() {
  document.body.classList.remove("shake"); void document.body.offsetWidth;
  document.body.classList.add("shake");
  for (const pad of (navigator.getGamepads ? navigator.getGamepads() : [])) {
    if (pad && pad.vibrationActuator) pad.vibrationActuator.playEffect("dual-rumble",
      { duration: 90, strongMagnitude: 1, weakMagnitude: 1 }).catch(() => {});
  }
  if (!audio) return;
  const o = audio.createOscillator(), g = audio.createGain(), t = audio.currentTime;
  o.type = phoneTone ? "square" : "sawtooth"; o.frequency.value = phoneTone ? 175 : 85;
  g.gain.setValueAtTime(1.0, t); g.gain.exponentialRampToValueAtTime(0.01, t + 0.11);
  o.connect(g); g.connect(audio.destination);
  o.start(t); o.stop(t + 0.12);
}
// A held tone for the whole pulse (phones): felt through the case.
function tone(ms) {
  if (!audio || !phoneTone) return;
  const o = audio.createOscillator(), g = audio.createGain(), t = audio.currentTime;
  o.type = "square"; o.frequency.value = 175; g.gain.value = 1.0;
  o.connect(g); g.connect(audio.destination);
  o.start(t); o.stop(t + ms / 1000);
}
function tick() { buzz(); hapticTick(); }
function hapticTick() {
  if (canVibrate) { navigator.vibrate(40); return; }
  const label = document.createElement("label");
  label.ariaHidden = "true"; label.style.display = "none";
  const input = document.createElement("input");
  input.type = "checkbox"; input.setAttribute("switch", "");
  label.appendChild(input); document.head.appendChild(label);
  label.click(); document.head.removeChild(label);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
// One strong pulse of `ms` milliseconds. Android: one long vibration. iPhone: a burst of
// rapid Taptic ticks (one tick alone is too faint to notice). Desktop: one buzz and shake.
async function pulse(ms) {
  buzz();
  if (canVibrate) { navigator.vibrate(ms); await sleep(ms); return; }
  if (desktop) { await sleep(ms); return; }
  tone(ms);
  const end = performance.now() + ms;
  while (performance.now() < end) { hapticTick(); await sleep(28); }
}
const $ = id => document.getElementById(id);
let level = "unknown", thing = "", seen = 0;

function show(l, what, ms) {
  level = l; thing = what || ""; seen = Date.now();
  document.body.className = l;
  $("word").textContent = l === "unknown" ? "?" : l;
  $("what").textContent = what || "";
  $("info").textContent = ms ? "looked in " + (ms / 1000).toFixed(1) + " s" : "";
}

// Morse by touch, the same way Helen sends words to the phone: a dot is one tick, a dash is
// two quick ticks, and three fast ticks first mean "message coming".
const MORSE = { A:".-", B:"-...", C:"-.-.", D:"-..", E:".", F:"..-.", G:"--.", H:"....", I:"..",
  J:".---", K:"-.-", L:".-..", M:"--", N:"-.", O:"---", P:".--.", Q:"--.-", R:".-.", S:"...",
  T:"-", U:"..-", V:"...-", W:".--", X:"-..-", Y:"-.--", Z:"--.." };
const T = { tickGap: 110, symbolGap: 380, letterGap: 900 };
async function alertTicks() { for (let i = 0; i < 3; i++) { await pulse(170); await sleep(110); } }
async function feelWord(word) {
  const letters = word.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 6);
  for (let i = 0; i < letters.length; i++) {
    const code = MORSE[letters[i]];
    $("morse").textContent = letters.slice(0, i + 1) + "   " + code;
    for (const s of code) {
      await pulse(90);
      if (s === "-") { await sleep(T.tickGap); await pulse(90); }
      await sleep(T.symbolGap);
    }
    await sleep(T.letterGap);
  }
  $("morse").textContent = "";
}

let stream = null;
async function openCam() {
  const cam = $("cam");
  stream = await navigator.mediaDevices.getUserMedia(
    { video: { facingMode: { ideal: "environment" } }, audio: false });
  cam.srcObject = stream; cam.hidden = false; await cam.play();
  if (cam.readyState < 2) await new Promise(r => { cam.onloadeddata = r; setTimeout(r, 1500); });
  await sleep(250);                 // let the exposure settle before the photo
}
function closeCam() {
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; $("cam").srcObject = null; }
}

async function feelOnce(told) {     // turn the latest answer into touch; returns what was told
  if (level === "stop") {
    const word = (thing.split(" ")[0] || "STOP");
    await alertTicks();                         // three strong pulses: danger, stop
    if (told !== "stop:" + word) {              // new danger: spell what it is, once
      await sleep(500);
      await feelWord(word);
      return "stop:" + word;
    }
    return told;
  }
  if (level === "near") {
    if (told !== "near") { await feelWord("N"); return "near"; }   // N = near
    await pulse(120);                           // one pulse while it stays near
    return told;
  }
  return level === "clear" ? "" : told;
}

async function run() {              // for ever: one photo, the answer, then the warning
  const cam = $("cam"), canvas = document.createElement("canvas");
  let told = "";
  for (;;) {
    const began = Date.now();
    try {
      if (!stream) await openCam();
      const w = 320, h = Math.round(w * cam.videoHeight / cam.videoWidth) || 240;
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(cam, 0, 0, w, h);
      if (iphone) closeCam();                   // camera off, so the iPhone may vibrate
      const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.6));
      const res = await fetch("/look", { method: "POST", body: blob });
      const a = await res.json();
      show(a.level, a.what, Date.now() - began);
    } catch (e) {
      if (iphone) closeCam();
      show("unknown", e && e.name === "NotAllowedError" ? "camera not allowed" : "laptop not reachable");
      await sleep(800);
    }
    if (iphone) await sleep(120);
    told = await feelOnce(told);
    await sleep(level === "stop" ? 300 : 500);
  }
}

$("start").onclick = async () => {
  if (wantSound) audio = new (window.AudioContext || window.webkitAudioContext)();
  tick();                            // a first touch unlocks haptics on the iPhone
  try { await openCam(); }
  catch (e) { $("info").textContent = "Camera not allowed: " + e.message; return; }
  $("start").hidden = true; $("word").hidden = false; $("test").hidden = false;
  $("test").onclick = async () => {
    if (iphone) closeCam();
    for (let i = 0; i < 3; i++) { await pulse(250); await sleep(150); }
  };
  if (navigator.wakeLock) navigator.wakeLock.request("screen").catch(() => {});
  run();
};
</script></body></html>
"""


def laptop_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def make_certificate(address):
    """A throwaway self-signed certificate in a temp folder (camera pages need HTTPS)."""
    folder = Path(tempfile.mkdtemp(prefix="lookout-"))
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3",
         "-keyout", str(key), "-out", str(cert), "-subj", "/CN=Lookout",
         "-addext", "subjectAltName=IP:%s,IP:127.0.0.1,DNS:localhost" % address],
        check=True, capture_output=True)
    return cert, key


def main():
    p = argparse.ArgumentParser(description="Phone camera warns of a wall ahead by vibration.")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--quiet", action="store_true", help="the laptop does not speak the warning")
    p.add_argument("--receiver", default=os.environ.get("LOOKOUT_RECEIVER", ""),
                   help="address of the team's iPhone receiver server, e.g. http://localhost:8765 : "
                        "each new danger is sent there and the native iPhone app vibrates it in Morse "
                        "(real haptics). Its code is read from VEXO_RECEIVER_CODE if needed")
    a = p.parse_args()

    gemini = Gemini()
    voice = None if a.quiet else Voice(use_eleven=False)
    last = {"level": None, "spoke": 0.0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code, kind, body):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] == "/":
                self._reply(200, "text/html; charset=utf-8", PAGE.encode())
            else:
                self._reply(404, "text/plain", b"not found")

        def do_POST(self):
            if self.path != "/look":
                return self._reply(404, "text/plain", b"not found")
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= 2_000_000:
                return self._reply(400, "text/plain", b"send one small JPEG")
            jpeg = self.rfile.read(size)
            began = time.time()
            answer = look(gemini, jpeg)
            took = time.time() - began
            print("  %-7s %-18s %.1f s" % (answer["level"], answer["what"], took), flush=True)
            with lock:
                changed = answer["level"] != last["level"]
                last["level"] = answer["level"]
                speak = bool(voice and answer["level"] == "stop" and changed
                             and time.time() - last["spoke"] > 4)
                if speak:
                    last["spoke"] = time.time()
            if a.receiver and answer["level"] == "stop":
                word = (answer["what"].split() or ["STOP"])[0].upper()
                with lock:
                    due = word != last.get("sent") or time.time() - last.get("sent_at", 0) > 12
                    if due:
                        last["sent"], last["sent_at"] = word, time.time()
                if due:
                    ok = send_to_receiver(a.receiver, os.environ.get("VEXO_RECEIVER_CODE", ""), word)
                    print("    -> iPhone app: %s %s" % (word, "sent" if ok else "NOT sent (receiver unreachable)"),
                          flush=True)
            elif answer["level"] == "clear":
                with lock:
                    last["sent"] = None
            if speak:
                what = answer["what"] if answer["what"] not in ("", "unclear") else "Obstacle"
                voice.say("%s ahead" % what.capitalize())
            self._reply(200, "application/json", json.dumps(answer).encode())

    address = laptop_address()
    cert, key = make_certificate(address)
    server = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)

    print("Lookout is running. Sight: %s." % (
        "Gemini (%s)" % gemini.model if gemini.ready
        else "OFF (%s): every look will say unknown" % gemini.problem))
    print("On the phone (same Wi-Fi) open:  https://%s:%d" % (address, a.port))
    print("The first time, the phone warns about the certificate: Show details -> visit this website.")
    print("Then press Start and allow the camera. Ctrl+C stops.")
    if a.receiver:
        print("Dangers are also sent to the iPhone receiver app at %s (real haptics, in Morse)." % a.receiver)
    print("On this laptop instead:  https://localhost:%d  (each tick buzzes the speakers and shakes the screen)\n" % a.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
