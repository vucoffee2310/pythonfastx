import sys
import io
import asyncio
import subprocess
import aiohttp
import threading
import os
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
    PROVIDER: str = "assemblyai"
    # In production, use os.environ.get("DEEPGRAM_KEY")
    DEEPGRAM_KEY: str = "d6bf3bf38250b6370e424a0805f6ef915ae00bec"
    DEEPGRAM_URL: str = "https://manage.deepgram.com/storage/assets"
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

# --- LOGGING HELPER ---
def log(q: asyncio.Queue, msg: str):
    if q: q.put_nowait(msg + "\n")

def miner_log_monitor(pipe, q):
    """Reads raw stderr from yt-dlp and pushes to queue."""
    for line in iter(pipe.readline, b""):
        text = line.decode("utf-8", errors="ignore")
        if "[download]" in text:
            text = text.replace("[download]", "[MINER] ⛏️ ")
        elif "[youtube]" in text:
            text = text.replace("[youtube]", "[MINER] 🔎 ")
        elif "[info]" in text:
            text = text.replace("[info]", "[MINER] ℹ️ ")
        log(q, text.strip())

# --- CPU BOUND ---
def create_package(packets: List, input_stream, max_dur: float, fmt: str):
    output_mem = io.BytesIO()
    with av.open(output_mem, mode="w", format=fmt) as container:
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
            else:
                break
    output_mem.seek(0)
    size = round(output_mem.getbuffer().nbytes / 1024 / 1024, 2)
    return output_mem, cutoff_idx, size

# --- PACKAGER ---
def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                 target_url: str, cookies: str, extractor_args: str):
    
    # 1. Write Cookies to Temp File
    if cookies:
        try:
            with open(CONFIG.COOKIE_FILE, "w") as f:
                f.write(cookies)
            log(log_q, f"[SYSTEM] 🍪 Cookies written to {CONFIG.COOKIE_FILE}")
        except Exception as e:
            log(log_q, f"[ERROR] Failed to write cookies: {e}")

    # 2. Build Command
    # Default Args similar to user request
    cmd = [
        "yt-dlp", "-f", "ba", "-S", "+abr,+tbr,+size",
        "--http-chunk-size", "8M",
        "--limit-rate", "4M",
        "-o", "-",
    ]

    # Add Cookie File arg
    if cookies:
        cmd.extend(["--cookies", CONFIG.COOKIE_FILE])

    # Add Extractor Args (PO Token, Client, etc)
    if extractor_args:
        cmd.extend(["--extractor-args", extractor_args])
    else:
        # Default fallback if user sends nothing
        cmd.extend(["--extractor-args", "youtube:player_client=tv;playback_wait=2"])

    # Add URL
    cmd.append(target_url)

    log(log_q, f"[PACKAGER] 🏭 Starting: {target_url}")
    # log(log_q, f"[CMD] {' '.join(cmd)}") # Debug command
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q))
    log_thread.daemon = True
    log_thread.start()

    try:
        in_container = av.open(process.stdout, mode="r")
        in_stream = in_container.streams.audio[0]
        codec = in_stream.codec_context.name
        out_fmt = CODEC_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}"

        log(log_q, f"[PACKAGER] 📦 Raw Material: {codec} | Output: {out_fmt}")

        buffer = []
        box_id = 0

        for packet in in_container.demux(in_stream):
            if packet.dts is None: continue
            buffer.append(packet)
            
            curr_dur = float(packet.dts - buffer[0].dts) * in_stream.time_base
            if curr_dur >= CONFIG.packaging_threshold:
                log(log_q, f"[PACKAGER] 🎁 Bin full ({curr_dur:.0f}s). Sealing Box #{box_id}...")
                mem_file, cutoff, size = create_package(buffer, in_stream, CONFIG.CHUNK_DURATION, out_fmt)
                
                cargo = Cargo(mem_file, box_id, mime, size)
                asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)
                buffer = buffer[cutoff + 1 :]
                box_id += 1

        if buffer:
            log(log_q, "[PACKAGER] 🏁 Stream ended. Sealing final box...")
            mem_file, _, size = create_package(buffer, in_stream, float("inf"), out_fmt)
            cargo = Cargo(mem_file, box_id, mime, size)
            asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)

    except Exception as e:
        log(log_q, f"[PACKAGER ERROR] {e}")
    finally:
        process.kill()
        asyncio.run_coroutine_threadsafe(conveyor_belt.put(None), loop)

# --- SHIPPER ---
async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q: asyncio.Queue):
    cargo.buffer.seek(0)
    if CONFIG.PROVIDER == "assemblyai":
        url = CONFIG.ASSEMBLYAI_URL
        headers = {"Authorization": CONFIG.ASSEMBLYAI_KEY, "Content-Type": "application/octet-stream"}
    else:
        url = CONFIG.DEEPGRAM_URL
        headers = {"Authorization": f"Token {CONFIG.DEEPGRAM_KEY}", "Content-Type": cargo.mime_type}

    try:
        async with session.post(url, headers=headers, data=cargo.buffer) as resp:
            if resp.status >= 400:
                err = await resp.text()
                log(log_q, f"[SHIPPER] ❌ Upload Failed Box #{cargo.index}: {resp.status} {err}")
                return
            
            body = await resp.json()
            res_id = body.get("upload_url") if CONFIG.PROVIDER == "assemblyai" else (body.get("asset_id") or body.get("asset"))
            log(log_q, f"[SHIPPER] ✅ Delivered Box #{cargo.index} | {cargo.size_mb}MB | Ref: {res_id}")
    except Exception as e:
        log(log_q, f"[SHIPPER] ⚠️ Error Box #{cargo.index}: {e}")
    finally:
        cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue):
    log(log_q, f"[SHIPPER] 🚚 Logistics Partner: {CONFIG.PROVIDER.upper()}")
    async with aiohttp.ClientSession() as session:
        active_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            
            log(log_q, f"[SHIPPER] 🚚 Picked up Box #{cargo.index}. Shipping...")
            t = asyncio.create_task(ship_cargo(session, cargo, log_q))
            active_shipments.append(t)
            active_shipments = [x for x in active_shipments if not x.done()]
            
        if active_shipments:
            log(log_q, f"[SHIPPER] ⏳ Waiting for {len(active_shipments)} active shipments...")
            await asyncio.gather(*active_shipments)

# --- ENTRY POINT ---
async def run_fly_process(log_queue: asyncio.Queue, url: str, cookies: str, args: str):
    """Main Orchestrator called by FastAPI"""
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    
    log(log_queue, "--- 🏭 LOGISTICS SYSTEM STARTED ---")
    
    shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue))
    
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(pool, run_packager, loop, conveyor_belt, log_queue, url, cookies, args)
        
    await shipper_task
    log(log_queue, "--- ✅ ALL SHIPMENTS COMPLETE ---")
    log_queue.put_nowait(None) # Signal end of stream
