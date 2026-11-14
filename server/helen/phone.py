"""Link to the phone: a small web server the iPhone opens in Safari on the same Wi-Fi.

The page (ios/web/index.html) receives events over Server-Sent Events:
  {"type": "feel", "words": "COFFEE Q", "morse": "-.-. ..."}  -> vibrate Morse
  {"type": "say", "text": "...", "audio": "/audio/3.mp3"}       -> play the voice
  {"type": "heard", "text": "..."}                               -> show what was said
"""
import json
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent.parent / "ios" / "web" / "index.html"
PORT = 8765

_clients = []          # one queue per open phone page
_audio = {}            # id -> mp3 bytes (recent voice clips)
_lock = threading.Lock()


def send(event):
    """Send an event to every open phone page."""
    with _lock:
        for q in _clients:
            q.put(event)


def add_audio(mp3):
    """Keep a voice clip for the phone to fetch; returns its URL."""
    with _lock:
        n = len(_audio) + 1
        _audio[n] = mp3
        for old in [k for k in _audio if k < n - 20]:
            del _audio[old]
    return f"/audio/{n}.mp3"


def phones():
    with _lock:
        return len(_clients)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._reply(200, "text/html; charset=utf-8", PAGE.read_bytes())
        elif self.path.startswith("/audio/"):
            try:
                mp3 = _audio[int(self.path.split("/")[-1].split(".")[0])]
            except (KeyError, ValueError):
                return self._reply(404, "text/plain", b"gone")
            self._reply(200, "audio/mpeg", mp3)
        elif self.path == "/events":
            self._events()
        else:
            self._reply(404, "text/plain", b"not found")

    def _reply(self, code, kind, body):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        q = queue.Queue()
        with _lock:
            _clients.append(q)
        try:
            self.wfile.write(b'data: {"type": "hello"}\n\n')
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")     # keeps the connection open
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _lock:
                _clients.remove(q)


def laptop_address():
    """This laptop's address on the Wi-Fi, for the phone to open."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "localhost"
    finally:
        s.close()


def start():
    """Start the web server in the background; returns the address to open on the phone."""
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://{laptop_address()}:{PORT}"
