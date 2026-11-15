"""Prepare Vexo transcripts and deliver an ordered feed to the phone."""

import asyncio
import os
import secrets
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from compact import prepare
from morse import encode

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
RECEIVER_CODE = os.getenv("VEXO_RECEIVER_CODE", "").strip()
MESSAGES = deque(maxlen=300)
SEQUENCE = 0
SESSION = secrets.token_hex(8)


@asynccontextmanager
async def lifespan(app):
    async with httpx.AsyncClient(timeout=5.0) as client:
        app.state.openai = client
        app.state.turn_lock = asyncio.Lock()
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


class Transcript(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    compact: bool = True


def authorized(request: Request, x_vexo_code: Annotated[str | None, Header()] = None):
    # Mutating endpoints reject browser requests from unrelated origins.
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Use the Vexo receiver page.")
    if request.client and request.client.host in {"127.0.0.1", "::1"}:
        return
    if not RECEIVER_CODE or not secrets.compare_digest(RECEIVER_CODE.encode(), (x_vexo_code or "").encode()):
        raise HTTPException(401, "Enter the receiver code from the Mac.")


@app.get("/")
def index():
    return FileResponse(ROOT / "web/index.html")


@app.post("/encode", dependencies=[Depends(authorized)])
def encode_transcript(transcript: Transcript):
    return encode(transcript.text)


@app.post("/transcripts", dependencies=[Depends(authorized)])
async def add_transcript(transcript: Transcript, request: Request):
    global SEQUENCE
    async with request.app.state.turn_lock:
        result = await prepare(request.app.state.openai, transcript.text, transcript.compact)
        SEQUENCE += 1
        message = {"id": SEQUENCE, **result}
        MESSAGES.append(message)
        return message


@app.post("/replies", dependencies=[Depends(authorized)])
async def add_reply(transcript: Transcript, request: Request):
    global SEQUENCE
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Band replies are submitted on the Mac.")
    async with request.app.state.turn_lock:
        message = encode(transcript.text)
        SEQUENCE += 1
        reply = {
            "id": SEQUENCE, "kind": "reply", "original": message, "selected": message,
            "original_units": 0, "selected_units": 0, "status": "reply",
        }
        MESSAGES.append(reply)
        return reply


@app.get("/transcripts", dependencies=[Depends(authorized)])
async def read_transcripts(after: int = 0, session: str = ""):
    if session != SESSION:
        after = 0
    return {
        "session": SESSION,
        "latest": SEQUENCE,
        "missed": bool(MESSAGES and MESSAGES[0]["id"] > after + 1),
        "messages": [message for message in MESSAGES if message["id"] > after][:25],
    }
