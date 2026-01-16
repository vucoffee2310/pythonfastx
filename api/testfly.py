import sys
import io
import asyncio
import subprocess
import aiohttp
import threading
import os
import time
from typing import NamedTuple, List, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# Import av conditionally
try:
    import av
except ImportError:
    pass 

# --- CONFIGURATION ---
@dataclass(frozen=True)
class Config:
    # API Keys
    DEEPGRAM_KEY: str = "d6bf3bf38250b6370e424a0805f6ef915ae00bec"
    DEEPGRAM_URL: str = "https://api.deepgram.com/v1/listen"
    ASSEMBLYAI_KEY: str = "193053bc6ff84ba9aac2465506f47d48"
    ASSEMBLYAI_URL: str = "https://api.assemblyai.com/v2/upload"
    
    COOKIE_FILE: str = "/tmp/cookies.txt"
    CHUNK_DURATION: int = 1800
    BUFFER_TAIL: int = 600

    @property
    def packaging_threshold(self) -> int:
        return self.CHUNK_DURATION + self.BUFFER_TAIL

CONFIG = Config()
CODEC_MAP = {"opus": "webm", "aac": "mp4", "mp3": "mp3", "vorbis": "ogg"}

class Cargo(NamedTuple):
    buffer: io.BytesIO
    index: int
    mime_type: str
    size_mb: float

def log(q: asyncio.Queue, msg: str):
    if q: q.put_nowait(msg + "\n")

def miner_log_monitor(pipe, q):
    last_progress_time = 0.0
    try:
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            if not text: continue
            if "[download]" in text:
                now = time.time()
                if (now - last_progress_time) > 0.5:
                    log(q, text.replace("[download]", "[MINER] ⛏️ "))
                    last_progress_time = now
            else: log(q, text)
    except: pass

def create_package(packets: List, input_stream, max_dur: float, fmt: str):
    output_mem = io.BytesIO()
    with av.open(output_mem, mode="w", format=fmt, options={'strict': 'experimental'}) as container:
        stream = container.add_stream(input_stream.codec_context.name)
        stream.time_base = input_stream.time_base
        if input_stream.codec_context.extradata:
            stream.codec_context.extradata = input_stream.codec_context.extradata
        base_dts = packets[0].dts
        base_pts = packets[0].pts
        cutoff_idx = 0
        for i, pkt in enumerate(packets):
            rel_time = float(pkt.dts - base_dts) * input_stream.time_base
            if rel_time < max_dur:
                pkt.dts -= base_dts
                pkt.pts -= base_pts
                pkt.stream = stream
                container.mux(pkt)
                cutoff_idx = i
            else: break
    output_mem.seek(0)
    return output_mem, cutoff_idx, round(output_mem.getbuffer().nbytes / 1024 / 1024, 2)

def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                 target_url: str, cookies: str, chunk_size: str, limit_rate: str, 
                 player_clients: str, wait_time: str, po_token: str):
    if cookies:
        try:
            # FIX: Properly unescape both newlines and tabs from the input string
            formatted_cookies = cookies.replace(r"\n", "\n").replace(r"\t", "\t")
            with open(CONFIG.COOKIE_FILE, "w") as f: f.write(formatted_cookies)
        except: pass

    cmd = [sys.executable, "-m", "yt_dlp", "--newline", "-f", "ba", "-o", "-", "--http-chunk-size", chunk_size, "--limit-rate", limit_rate]
    if cookies: cmd.extend(["--cookies", CONFIG.COOKIE_FILE])
    
    # Add extractor args
    extractor_params = []
    if player_clients: extractor_params.append(f"player_client={player_clients}")
    if wait_time: extractor_params.append(f"playback_wait={wait_time}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    if extractor_params:
        cmd.extend(["--extractor-args", f"youtube:{';'.join(extractor_params)}"])

    cmd.append(target_url)

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q), daemon=True).start()

    in_container = None
    try:
        in_container = av.open(process.stdout, mode="r")
        in_stream = in_container.streams.audio[0]
        out_fmt = CODEC_MAP.get(in_stream.codec_context.name, "matroska")
        
        buffer, box_id = [], 0
        for packet in in_container.demux(in_stream):
            if packet.dts is None: continue
            buffer.append(packet)
            curr_dur = float(packet.dts - buffer[0].dts) * in_stream.time_base
            if curr_dur >= CONFIG.packaging_threshold:
                mem_file, cutoff, size = create_package(buffer, in_stream, CONFIG.CHUNK_DURATION, out_fmt)
                asyncio.run_coroutine_threadsafe(conveyor_belt.put(Cargo(mem_file, box_id, f"audio/{out_fmt}", size)), loop)
                buffer, box_id = buffer[cutoff + 1 :], box_id + 1

        if buffer:
            mem_file, _, size = create_package(buffer, in_stream, float("inf"), out_fmt)
            asyncio.run_coroutine_threadsafe(conveyor_belt.put(Cargo(mem_file, box_id, f"audio/{out_fmt}", size)), loop)
    except Exception as e: log(log_q, f"[PACKAGER ERROR] {e}")
    finally:
        if in_container: in_container.close()
        process.terminate()
        asyncio.run_coroutine_threadsafe(conveyor_belt.put(None), loop)

async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q: asyncio.Queue, provider: str):
    cargo.buffer.seek(0)
    if provider == "assemblyai":
        url, headers = CONFIG.ASSEMBLYAI_URL, {"Authorization": CONFIG.ASSEMBLYAI_KEY, "Content-Type": "application/octet-stream"}
    else:
        url, headers = CONFIG.DEEPGRAM_URL, {"Authorization": f"Token {CONFIG.DEEPGRAM_KEY}", "Content-Type": cargo.mime_type}

    try:
        async with session.post(url, headers=headers, data=cargo.buffer) as resp:
            body = await resp.json()
            res_id = body.get("upload_url") if provider == "assemblyai" else (body.get("request_id") or "OK")
            log(log_q, f"[SHIPPER] ✅ Box #{cargo.index} ({provider}) | Ref: {res_id}")
    except Exception as e: log(log_q, f"[SHIPPER ERROR] {e}")
    finally: cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, provider: str):
    async with aiohttp.ClientSession() as session:
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            await ship_cargo(session, cargo, log_q, provider)

async def run_fly_process(log_queue: asyncio.Queue, url: str, cookies: str, chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str, provider: str):
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue, provider))
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(pool, run_packager, loop, conveyor_belt, log_queue, url, cookies, chunk_size, limit_rate, player_clients, wait_time, po_token)
    await shipper_task
    log(log_queue, "--- ✅ COMPLETE ---")
    log_queue.put_nowait(None)
