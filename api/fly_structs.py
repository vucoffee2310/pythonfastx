import io
import time
import json
import asyncio
from typing import NamedTuple, Optional
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    CHUNK_DURATION: int = 1800
    BUFFER_TAIL: int = 600

    @property
    def packaging_threshold(self) -> int:
        return self.CHUNK_DURATION + self.BUFFER_TAIL

CONFIG = Config()
CODEC_MAP = {"opus": "webm", "aac": "mp4", "mp3": "mp3", "vorbis": "ogg"}

@dataclass
class SessionContext:
    provider: str
    deepgram_key: Optional[str]
    assemblyai_key: Optional[str]
    mode: str
    cookie_file: str

class Cargo(NamedTuple):
    buffer: io.BytesIO
    index: int
    mime_type: str
    size_mb: float

def log_dispatch(q: asyncio.Queue, ctx: SessionContext, event_type: str, payload: dict = None, text: str = None):
    """
    Standardized Event Emitter
    Events: status, asset, error, keepalive
    """
    if not q: return

    packet = {
        "type": event_type,
        "timestamp": time.time(),
        "payload": payload or {}
    }
    
    if text and "message" not in packet["payload"]:
        packet["payload"]["message"] = text

    # 1. Handle DATA Mode (Strict JSON)
    if ctx.mode == "data":
        if event_type in ["asset", "error", "keepalive"]:
            q.put_nowait(json.dumps(packet) + "\n")
        return

    # 2. Handle DEBUG Mode (Verbose Text + JSON)
    if text:
        q.put_nowait(f"[{event_type.upper()}] {text}\n")
    
    if event_type in ["asset", "error", "keepalive"] or payload:
        q.put_nowait(json.dumps(packet) + "\n")