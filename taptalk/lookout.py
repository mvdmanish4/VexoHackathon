"""Lookout: the phone's camera warns a deaf-blind person of a wall or obstacle ahead, by touch.

The laptop serves one web page. The phone opens it, its rear camera sends a small photo
about once a second, Gemini says whether something is in the way, and the phone vibrates:

    stop  (about 1 m or closer)   three fast ticks, then the obstacle spelled in Morse
                                  (WALL = .-- .- .-.. .-..), then three fast ticks repeating
    near  (about 1 to 3 m)        N in Morse (-.), then one slow tick repeating
    clear                         nothing

Morse is felt the same way as in Helen: a dot is one tick, a dash is two quick ticks.

The laptop also says "Wall ahead" out loud once, so people nearby know why the person stopped.

    python3 lookout.py            then open the printed https:// address on the phone

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
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sponsors import GEMINI_BASE, THINKING_STYLES, Gemini, Voice, _request

LOOK_INSTRUCTIONS = (
    "This photo is the view straight ahead of a blind person who is walking slowly, taken "
    "from a phone held at chest height. Decide if a wall, door, person, furniture, step or "
    "other obstacle is in their path. Answer with JSON only: "
    '{"level": "stop" | "near" | "clear", "what": "<ONE short word: wall, door, person, chair, table, step, pole>"}. '
    '"stop" = the obstacle fills most of the view or is within about 1 metre. '
    '"near" = it is about 1 to 3 metres ahead. '
    '"clear" = nothing in the path for 3 metres or more (then "what" is ""). '
    "If the photo is too dark or blurred to tell, answer stop with what = unclear."
)
LEVELS = ("stop", "near", "clear")
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
                return {"level": level, "what": str(answer.get("what", ""))[:30]}
            if candidate.get("finishReason") != "MAX_TOKENS":
                return unknown
        except urllib.error.HTTPError as e:
            if e.code != 400:
                return {"level": "unknown", "what": "Gemini status %d" % e.code}
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
            return {"level": "unknown", "what": "Gemini not reachable"}
        style += 1
    return unknown


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Lookout</title>
<style>
  html, body { margin: 0; height: 100%; font-family: -apple-system, system-ui, sans-serif; }
  body { background: #222; color: #fff; display: flex; flex-direction: column;
         align-items: center; justify-content: center; text-align: center; transition: background .15s; }
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
<div id="word" hidden></div><div id="what"></div><div id="morse"></div><div id="info"></div>
<video id="cam" playsinline muted hidden></video>
<script>
// Haptics: iPhone (iOS 18+) ticks when a hidden "switch" is flipped; Android uses vibrate.
const canVibrate = typeof navigator.vibrate === "function";
function tick() {
  if (canVibrate) { navigator.vibrate(40); return; }
  const label = document.createElement("label");
  label.ariaHidden = "true"; label.style.display = "none";
  const input = document.createElement("input");
  input.type = "checkbox"; input.setAttribute("switch", "");
  label.appendChild(input); document.head.appendChild(label);
  label.click(); document.head.removeChild(label);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
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
async function alertTicks() { for (let i = 0; i < 3; i++) { tick(); await sleep(130); } }
async function feelWord(word) {
  const letters = word.toUpperCase().replace(/[^A-Z]/g, "").slice(0, 6);
  for (let i = 0; i < letters.length; i++) {
    const code = MORSE[letters[i]];
    $("morse").textContent = letters.slice(0, i + 1) + "   " + code;
    for (const s of code) {
      tick();
      if (s === "-") { await sleep(T.tickGap); tick(); }
      await sleep(T.symbolGap);
    }
    await sleep(T.letterGap);
  }
  $("morse").textContent = "";
}

async function feel() {             // runs for ever: turns what is ahead into touch
  let told = "";                    // the warning already spelled out
  for (;;) {
    if (Date.now() - seen > 6000 && level !== "unknown") show("unknown", "no recent look");
    if (level === "stop") {
      const word = (thing.split(" ")[0] || "STOP");
      await alertTicks();                       // three fast ticks: danger, stop
      if (told !== "stop:" + word) {            // new obstacle: spell what it is, once
        told = "stop:" + word;
        await sleep(500);
        await feelWord(word);
      } else await sleep(1000);                 // still there: keep warning
    } else if (level === "near") {
      if (told !== "near") { told = "near"; await feelWord("N"); }   // N = near
      else { tick(); await sleep(1500); }       // one slow tick while it stays near
    } else { if (level === "clear") told = ""; await sleep(150); }
  }
}

async function watch() {            // runs for ever: one photo, wait for the answer, repeat
  const cam = $("cam"), canvas = document.createElement("canvas");
  for (;;) {
    const began = Date.now();
    try {
      const w = 320, h = Math.round(w * cam.videoHeight / cam.videoWidth) || 240;
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(cam, 0, 0, w, h);
      const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.6));
      const res = await fetch("/look", { method: "POST", body: blob });
      const a = await res.json();
      show(a.level, a.what, Date.now() - began);
    } catch (e) { show("unknown", "laptop not reachable"); }
    await sleep(Math.max(0, 700 - (Date.now() - began)));
  }
}

$("start").onclick = async () => {
  tick();                            // a first touch unlocks haptics on the iPhone
  try {
    const stream = await navigator.mediaDevices.getUserMedia(
      { video: { facingMode: { ideal: "environment" } }, audio: false });
    const cam = $("cam"); cam.srcObject = stream; cam.hidden = false; await cam.play();
  } catch (e) { $("info").textContent = "Camera not allowed: " + e.message; return; }
  $("start").hidden = true; $("word").hidden = false;
  if (navigator.wakeLock) navigator.wakeLock.request("screen").catch(() => {});
  feel(); watch();
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
            if self.path == "/":
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
    print("Then press Start and allow the camera. Ctrl+C stops.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
