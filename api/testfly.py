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
    HAS_AV = True
except ImportError:
    HAS_AV = False

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

# --- THREAD-SAFE LOGGING ---
def ts_log(loop: asyncio.AbstractEventLoop, q: asyncio.Queue, msg: str):
    """Thread-safe logging helper."""
    if q and loop:
        loop.call_soon_threadsafe(q.put_nowait, msg + "\n")

def miner_log_monitor(pipe, loop, q):
    """Reads raw stderr from yt-dlp in a thread, safely pushing to async queue."""
    last_progress_time = 0.0
    try:
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            if not text: continue

            if "[download]" in text:
                clean_text = text.replace("[download]", "[MINER] ⛏️ ").strip()
                now = time.time()
                if (now - last_progress_time) > 0.5:
                    ts_log(loop, q, clean_text)
                    last_progress_time = now
            elif "[youtube]" in text:
                ts_log(loop, q, text.replace("[youtube]", "[MINER] 🔎 "))
            elif "[info]" in text:
                ts_log(loop, q, text.replace("[info]", "[MINER] ℹ️ "))
            else:
                ts_log(loop, q, text)
    except ValueError:
        pass 

# --- CPU BOUND ---
def create_package(packets: List, input_stream, max_dur: float, fmt: str):
    if not HAS_AV: return None, 0, 0
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
            else:
                break
    output_mem.seek(0)
    size = round(output_mem.getbuffer().nbytes / 1024 / 1024, 2)
    return output_mem, cutoff_idx, size

# --- PACKAGER ---
def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                 target_url: str, cookies: str, 
                 chunk_size: str, limit_rate: str, 
                 player_clients: str, wait_time: str, po_token: str):
    
    # Helper for logging inside this thread
    def log(msg): ts_log(loop, log_q, msg)

    if not HAS_AV:
        log("[ERROR] ❌ PyAV library is missing. Cannot process audio stream.")
        asyncio.run_coroutine_threadsafe(conveyor_belt.put(None), loop)
        return

    # 1. Write Cookies
    if cookies:
        try:
            formatted_cookies = cookies.replace(r"\n", "\n").replace(r"\t", "\t")
            with open(CONFIG.COOKIE_FILE, "w") as f:
                f.write(formatted_cookies)
            log(f"[SYSTEM] 🍪 Cookies processed to {CONFIG.COOKIE_FILE}")
        except Exception as e:
            log(f"[ERROR] Failed to write cookies: {e}")

    # 2. Extractor Args
    extractor_params = []
    if player_clients: extractor_params.append(f"player_client={player_clients}")
    if wait_time: extractor_params.append(f"playback_wait={wait_time}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    
    extractor_string = f"youtube:{';'.join(extractor_params)}" if extractor_params else ""

    # 3. Build Command
    cmd = [
        sys.executable, "-m", "yt_dlp", 
        "--newline",
        "-f", "ba", 
        "-S", "+abr,+tbr,+size",
        "--http-chunk-size", chunk_size,
        "--limit-rate", limit_rate,
        "-o", "-"
    ]

    if cookies: cmd.extend(["--cookies", CONFIG.COOKIE_FILE])
    if extractor_string: cmd.extend(["--extractor-args", extractor_string])

    cmd.append(target_url)

    printable_cmd = " ".join([f"'{c}'" if " " in c or ";" in c else c for c in cmd])
    log(f"[PACKAGER] 🏭 Starting: {target_url}")
    log(f"[COMMAND] ⌨️  {printable_cmd}")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Pass loop to the miner logger
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, loop, log_q))
    log_thread.daemon = True
    log_thread.start()

    log("[PACKAGER] ⏳ Waiting for stream data...")

    in_container = None

    try:
        # Check if process crashed immediately
        time.sleep(1) # Brief wait to catch early exits
        if process.poll() is not None:
             raise Exception(f"Process finished immediately with code {process.returncode}")

        in_container = av.open(process.stdout, mode="r")
        if not in_container.streams.audio:
            raise Exception("No audio stream found in input.")

        in_stream = in_container.streams.audio[0]
        codec = in_stream.codec_context.name
        out_fmt = CODEC_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}"

        log(f"[PACKAGER] ✅ Stream Connected! Codec: {codec} | Container: {out_fmt}")

        buffer = []
        box_id = 0

        for packet in in_container.demux(in_stream):
            if packet.dts is None: continue
            buffer.append(packet)
            
            curr_dur = float(packet.dts - buffer[0].dts) * in_stream.time_base
            if curr_dur >= CONFIG.packaging_threshold:
                log(f"[PACKAGER] 🎁 Bin full ({curr_dur:.0f}s). Sealing Box #{box_id}...")
                mem_file, cutoff, size = create_package(buffer, in_stream, CONFIG.CHUNK_DURATION, out_fmt)
                
                if mem_file:
                    cargo = Cargo(mem_file, box_id, mime, size)
                    asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)
                    buffer = buffer[cutoff + 1 :]
                    box_id += 1

        if buffer:
            log("[PACKAGER] 🏁 Stream ended. Sealing final box...")
            mem_file, _, size = create_package(buffer, in_stream, float("inf"), out_fmt)
            if mem_file:
                cargo = Cargo(mem_file, box_id, mime, size)
                asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)

    except Exception as e:
        log(f"[PACKAGER ERROR] 💥 {e}")
    finally:
        if in_container:
            try: in_container.close()
            except: pass
        
        if process:
            if process.stdout: 
                try: process.stdout.close()
                except: pass
            if process.stderr: 
                try: process.stderr.close()
                except: pass

            if process.poll() is None:
                log("[CLEANUP] 🛑 Terminating downloader process...")
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill()
            else:
                 log(f"[CLEANUP] 🛑 Downloader exited with code {process.returncode}")

        asyncio.run_coroutine_threadsafe(conveyor_belt.put(None), loop)

# --- SHIPPER ---
async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q: asyncio.Queue):
    # Loop context is valid here (async func), so direct put_nowait is ok
    cargo.buffer.seek(0)
    
    # Determine Provider based on GLOBAL CONFIG (simplified for demo)
    # Ideally passed in payload, but using Config defaults
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
                log_q.put_nowait(f"[SHIPPER] ❌ Upload Failed Box #{cargo.index}: {resp.status} {err}\n")
                return
            
            body = await resp.json()
            
            if CONFIG.PROVIDER == "assemblyai":
                res_url = body.get("upload_url")
            else:
                asset_id = body.get("asset_id") or body.get("asset")
                res_url = f"https://manage.deepgram.com/storage/assets/{asset_id}" if asset_id else "ID Missing"

            # Critical format for extension parsing
            log_q.put_nowait(f"✅ Box #{cargo.index}: {res_url}\n")
            
    except Exception as e:
        log_q.put_nowait(f"[SHIPPER] ⚠️ Error Box #{cargo.index}: {e}\n")
    finally:
        cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue):
    log_q.put_nowait(f"[SHIPPER] 🚚 Logistics Partner: {CONFIG.PROVIDER.upper()}\n")
    async with aiohttp.ClientSession() as session:
        active_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            
            log_q.put_nowait(f"[SHIPPER] 🚚 Picked up Box #{cargo.index}. Shipping...\n")
            t = asyncio.create_task(ship_cargo(session, cargo, log_q))
            active_shipments.append(t)
            active_shipments = [x for x in active_shipments if not x.done()]
            
        if active_shipments:
            log_q.put_nowait(f"[SHIPPER] ⏳ Waiting for {len(active_shipments)} active shipments...\n")
            await asyncio.gather(*active_shipments)

# --- ENTRY POINT ---
async def run_fly_process(log_queue: asyncio.Queue, url: str, cookies: str, 
                          chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str):
    """Main Orchestrator called by FastAPI"""
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    
    log_queue.put_nowait("--- 🏭 LOGISTICS SYSTEM STARTED ---\n")
    
    # Update Config Singleton (Temporary Hack for Session Scope)
    # Note: In a real high-concurrency app, pass config objects instead of using global
    # But for this Vercel function, it's acceptable.
    
    shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue))
    
    with ThreadPoolExecutor(max_workers=1) as pool:
        # Pass loop to worker for thread-safe logging
        await loop.run_in_executor(
            pool, run_packager, loop, conveyor_belt, log_queue, 
            url, cookies, chunk_size, limit_rate, player_clients, wait_time, po_token
        )
        
    await shipper_task
    log_queue.put_nowait("--- ✅ ALL SHIPMENTS COMPLETE ---\n")
    log_queue.put_nowait(None) # Signal end of stream
