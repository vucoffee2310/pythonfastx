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
    """Reads raw stderr from yt-dlp, filters spam, and pushes to queue."""
    last_progress_time = 0.0
    
    try:
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            
            if not text: continue

            if "[download]" in text:
                # Clean up the tag
                clean_text = text.replace("[download]", "[MINER] ⛏️ ").strip()
                
                # Rate Limit: Only log progress every 0.5 seconds to prevent spam
                now = time.time()
                if (now - last_progress_time) > 0.5:
                    log(q, clean_text)
                    last_progress_time = now
                    
            elif "[youtube]" in text:
                log(q, text.replace("[youtube]", "[MINER] 🔎 "))
            elif "[info]" in text:
                log(q, text.replace("[info]", "[MINER] ℹ️ "))
            else:
                # Pass through other logs (errors, warnings, etc.) immediately
                log(q, text)
    except ValueError:
        pass # Handle closed pipe errors during shutdown

# --- CPU BOUND ---
def create_package(packets: List, input_stream, max_dur: float, fmt: str):
    output_mem = io.BytesIO()
    
    # Using strict='experimental' to allow Opus/Vorbis in containers that consider it experimental
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
    
    # 1. Write Cookies
    if cookies:
        try:
            formatted_cookies = cookies.replace(r"\n", "\n").replace(r"\t", "\t")
            with open(CONFIG.COOKIE_FILE, "w") as f:
                f.write(formatted_cookies)
            log(log_q, f"[SYSTEM] 🍪 Cookies processed to {CONFIG.COOKIE_FILE}")
        except Exception as e:
            log(log_q, f"[ERROR] Failed to write cookies: {e}")

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

    # --- REQUIREMENT 3: Log the Full Command ---
    # We join carefully to make it readable, adding quotes if spaces exist
    printable_cmd = " ".join([f"'{c}'" if " " in c or ";" in c else c for c in cmd])
    log(log_q, f"[PACKAGER] 🏭 Starting: {target_url}")
    log(log_q, f"[COMMAND] ⌨️  {printable_cmd}")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q))
    log_thread.daemon = True
    log_thread.start()

    log(log_q, "[PACKAGER] ⏳ Waiting for stream data...")

    in_container = None

    try:
        # Check if process crashed immediately
        if process.poll() is not None:
             raise Exception(f"Process finished unexpectedly with code {process.returncode}")

        in_container = av.open(process.stdout, mode="r")
        in_stream = in_container.streams.audio[0]
        codec = in_stream.codec_context.name
        out_fmt = CODEC_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}"

        log(log_q, f"[PACKAGER] ✅ Stream Connected! Codec: {codec} | Container: {out_fmt}")

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
        log(log_q, f"[PACKAGER ERROR] 💥 {e}")
    finally:
        # --- REQUIREMENT 1 & 2: Proper Stream Closure ---
        
        # 1. Close the AV Container
        if in_container:
            try:
                in_container.close()
                log(log_q, "[CLEANUP] 🔒 Audio container closed.")
            except Exception:
                pass
        
        # 2. Terminate the subprocess aggressively but cleanly
        if process:
            # Close stdout to break the pipe from the consumer side
            if process.stdout:
                try: 
                    process.stdout.close()
                except Exception: 
                    pass
            
            # Close stderr
            if process.stderr:
                try:
                    process.stderr.close()
                except Exception:
                    pass

            # Handle process termination
            if process.poll() is None:
                log(log_q, "[CLEANUP] 🛑 Terminating downloader process...")
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    log(log_q, "[CLEANUP] 🔪 Force killing downloader...")
                    process.kill()
            else:
                 log(log_q, f"[CLEANUP] 🛑 Downloader exited with code {process.returncode}")

        # Signal end of queue
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
            
            # --- MODIFIED LOGGING HERE ---
            display_ref = res_id
            # Construct full URL for Deepgram if only ID is returned
            if CONFIG.PROVIDER != "assemblyai" and res_id and not str(res_id).startswith("http"):
                display_ref = f"{CONFIG.DEEPGRAM_URL}/{res_id}"
                
            log(log_q, f"✅ Box #{cargo.index}: Asset {display_ref}")
            
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
async def run_fly_process(log_queue: asyncio.Queue, url: str, cookies: str, 
                          chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str):
    """Main Orchestrator called by FastAPI"""
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    
    log(log_queue, "--- 🏭 LOGISTICS SYSTEM STARTED ---")
    
    shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue))
    
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(
            pool, run_packager, loop, conveyor_belt, log_queue, 
            url, cookies, chunk_size, limit_rate, player_clients, wait_time, po_token
        )
        
    await shipper_task
    log(log_queue, "--- ✅ ALL SHIPMENTS COMPLETE ---")
    log_queue.put_nowait(None) # Signal end of stream
