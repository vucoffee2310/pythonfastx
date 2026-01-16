import sys
import io
import asyncio
import subprocess
import aiohttp
import threading
import os
import time
import uuid
import shutil
from typing import NamedTuple, List, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# Import av conditionally
try:
    import av
except ImportError:
    pass 

# --- CONFIGURATION ---
@dataclass
class Config:
    PROVIDER: str = "assemblyai" # or "deepgram"
    
    # API KEYS (Load from Env for security, fallback to defaults for testing)
    DEEPGRAM_KEY: str = os.environ.get("DEEPGRAM_KEY", "d6bf3bf38250b6370e424a0805f6ef915ae00bec")
    # Note: Deepgram upload URL is often specific to the project/version
    DEEPGRAM_URL: str = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true" 
    
    ASSEMBLYAI_KEY: str = os.environ.get("ASSEMBLYAI_KEY", "193053bc6ff84ba9aac2465506f47d48")
    ASSEMBLYAI_URL: str = "https://api.assemblyai.com/v2/upload"
    
    # Reduced default duration for testing stability (3 minutes)
    CHUNK_DURATION: int = 180 
    # Buffer tail to ensure we have enough overlap or data
    BUFFER_TAIL: int = 30

    @property
    def packaging_threshold(self) -> int:
        return self.CHUNK_DURATION + self.BUFFER_TAIL

CONFIG = Config()
# Mapping codecs to containers that support streaming
CODEC_MAP = {"opus": "webm", "aac": "adts", "mp3": "mp3", "vorbis": "ogg", "flac": "flac"}

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
    if not pipe: return
    last_progress_time = 0.0
    
    try:
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            if not text: continue

            if "[download]" in text:
                # Rate Limit: Only log progress every 1.0 seconds
                now = time.time()
                if (now - last_progress_time) > 1.0:
                    clean_text = text.replace("[download]", "⛏️ ").strip()
                    log(q, f"[MINER] {clean_text}")
                    last_progress_time = now
            elif "[youtube]" in text:
                log(q, f"[MINER] 🔎 {text.replace('[youtube]', '').strip()}")
            elif "ERROR:" in text:
                log(q, f"[MINER ERROR] ❌ {text}")
            else:
                # Filter out verbose FFmpeg logs if they appear
                if not text.startswith("frame="):
                    log(q, f"[MINER] {text}")
    except ValueError:
        pass # Pipe closed

# --- CPU BOUND ---
def create_package(packets: List, input_stream, max_dur: float, fmt: str):
    output_mem = io.BytesIO()
    
    # Use 'strict': 'experimental' for Opus in MP4/WebM contexts if needed
    # 'frag_keyframe+empty_moov' is crucial for fragmented mp4 streaming, 
    # but for simple file uploads, standard defaults usually work.
    mux_options = {'strict': 'experimental'}
    
    try:
        with av.open(output_mem, mode="w", format=fmt, options=mux_options) as container:
            # COPY STREAM SETTINGS via template (More robust than manual assignment)
            stream = container.add_stream(template=input_stream)
            
            # Reset Timestamps for the new container
            base_dts = packets[0].dts
            base_pts = packets[0].pts
            cutoff_idx = 0

            for i, pkt in enumerate(packets):
                if pkt.dts is None: continue
                
                # Calculate relative time in seconds
                rel_time = float(pkt.dts - base_dts) * input_stream.time_base
                
                if rel_time < max_dur:
                    # Re-calculate timestamps relative to 0 for this chunk
                    pkt.dts = pkt.dts - base_dts
                    pkt.pts = pkt.pts - base_pts
                    pkt.stream = stream
                    
                    # Force keyframe for first packet to ensure playability
                    if i == 0:
                        pkt.is_keyframe = True
                        
                    container.mux(pkt)
                    cutoff_idx = i
                else:
                    break
                    
    except Exception as e:
        print(f"Muxing error: {e}")
        return None, 0, 0

    output_mem.seek(0)
    size = round(output_mem.getbuffer().nbytes / 1024 / 1024, 2)
    return output_mem, cutoff_idx, size

# --- PACKAGER ---
def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                 target_url: str, cookies: str, 
                 chunk_size: str, limit_rate: str, 
                 player_clients: str, wait_time: str, po_token: str):
    
    # 1. Unique Cookie File to prevent concurrency collisions
    cookie_file = f"/tmp/cookies_{uuid.uuid4()}.txt"
    if cookies:
        try:
            formatted_cookies = cookies.replace(r"\n", "\n").replace(r"\t", "\t")
            with open(cookie_file, "w") as f:
                f.write(formatted_cookies)
            log(log_q, f"[SYSTEM] 🍪 Cookies loaded.")
        except Exception as e:
            log(log_q, f"[ERROR] Failed to write cookies: {e}")

    # 2. Build Command
    # We force 'mkv' (Matroska) container for the pipe because it's streamable 
    # and PyAV detects it easily without seeking.
    cmd = [
        sys.executable, "-m", "yt_dlp", 
        "--newline",
        "--ignore-errors",
        "--no-progress", # We parse output manually, but this reduces spam
        "-f", "ba/b",    # Best audio
        "--remux-video", "mkv", # FORCE MKV container for pipe stability
        "-o", "-"        # Output to stdout
    ]
    
    # Throttle args
    if chunk_size: cmd.extend(["--http-chunk-size", chunk_size])
    if limit_rate: cmd.extend(["--limit-rate", limit_rate])

    # Extractor args
    extractor_params = []
    if player_clients: extractor_params.append(f"player_client={player_clients}")
    if wait_time: extractor_params.append(f"playback_wait={wait_time}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    
    if extractor_params: cmd.extend(["--extractor-args", f"youtube:{';'.join(extractor_params)}"])
    if cookies and os.path.exists(cookie_file): cmd.extend(["--cookies", cookie_file])

    cmd.append(target_url)

    log(log_q, f"[PACKAGER] 🏭 Starting Stream...")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q))
    log_thread.daemon = True
    log_thread.start()

    log(log_q, "[PACKAGER] ⏳ Probing stream (this may take a few seconds)...")

    try:
        # Open the stream with PyAV
        # 'options' helps PyAV not hang on pipes
        in_container = av.open(process.stdout, mode="r", options={'probesize': '1024', 'analyzeduration': '0'})
        in_stream = in_container.streams.audio[0]
        
        # Determine output format
        codec = in_stream.codec_context.name
        # Default to webm if opus, otherwise mkv or mp3
        out_fmt = CODEC_MAP.get(codec, "webm") 
        if codec == 'aac': out_fmt = 'adts' # ADTS is the container for streaming AAC
        
        mime = f"audio/{out_fmt}"
        if out_fmt == 'adts': mime = 'audio/aac'

        log(log_q, f"[PACKAGER] ✅ Locked Codec: {codec} | Muxing to: {out_fmt}")

        buffer = []
        box_id = 0
        
        # Demux Loop
        for packet in in_container.demux(in_stream):
            if packet.dts is None: continue
            
            # Ensure packet belongs to our stream
            if packet.stream.index != in_stream.index: continue
            
            buffer.append(packet)
            
            # Check duration
            if len(buffer) > 10: # Only check after some packets
                curr_dur = float(packet.dts - buffer[0].dts) * in_stream.time_base
                
                if curr_dur >= CONFIG.packaging_threshold:
                    log(log_q, f"[PACKAGER] 🎁 Segmenting {curr_dur:.0f}s chunk...")
                    mem_file, cutoff, size = create_package(buffer, in_stream, CONFIG.CHUNK_DURATION, out_fmt)
                    
                    if mem_file:
                        cargo = Cargo(mem_file, box_id, mime, size)
                        asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)
                        log(log_q, f"[PACKAGER] 📤 Queued Box #{box_id} ({size}MB)")
                        box_id += 1
                        
                        # Slice buffer (keep tail)
                        buffer = buffer[cutoff + 1 :]
                    else:
                        log(log_q, f"[PACKAGER] ⚠️ Muxing failed for Box #{box_id}")
                        buffer = [] # Clear on error to prevent overflow

        # Final Buffer
        if buffer:
            log(log_q, "[PACKAGER] 🏁 Stream ended. Sealing final box...")
            mem_file, _, size = create_package(buffer, in_stream, float("inf"), out_fmt)
            if mem_file:
                cargo = Cargo(mem_file, box_id, mime, size)
                asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)

    except av.AVError as e:
        log(log_q, f"[PACKAGER AV ERROR] {e}")
    except Exception as e:
        log(log_q, f"[PACKAGER ERROR] {e}")
    finally:
        log(log_q, "[PACKAGER] 🛑 Process Terminated")
        process.kill()
        # Clean up cookies
        if os.path.exists(cookie_file):
            try: os.remove(cookie_file)
            except: pass
        
        asyncio.run_coroutine_threadsafe(conveyor_belt.put(None), loop)

# --- SHIPPER ---
async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q: asyncio.Queue):
    cargo.buffer.seek(0)
    
    if CONFIG.PROVIDER == "assemblyai":
        url = CONFIG.ASSEMBLYAI_URL
        headers = {"Authorization": CONFIG.ASSEMBLYAI_KEY, "Content-Type": "application/octet-stream"}
    else:
        # Deepgram Logic
        url = "https://api.deepgram.com/v1/listen?model=nova-2"
        headers = {
            "Authorization": f"Token {CONFIG.DEEPGRAM_KEY}", 
            "Content-Type": cargo.mime_type
        }

    try:
        async with session.post(url, headers=headers, data=cargo.buffer) as resp:
            text_resp = await resp.text()
            if resp.status >= 400:
                log(log_q, f"[SHIPPER] ❌ Upload Failed #{cargo.index}: {resp.status}")
                # Optional: log detailed error if needed, but keep it brief for UI
                # log(log_q, f"Err: {text_resp[:100]}")
                return
            
            try:
                body = await resp.json()
                # Try to find an ID in common API responses
                res_id = body.get("upload_url") or body.get("request_id") or body.get("metadata", {}).get("request_id") or "OK"
                log(log_q, f"[SHIPPER] ✅ Delivered Box #{cargo.index} | {cargo.size_mb}MB | ID: ...{str(res_id)[-6:]}")
            except:
                log(log_q, f"[SHIPPER] ✅ Delivered Box #{cargo.index} (No JSON resp)")
                
    except Exception as e:
        log(log_q, f"[SHIPPER] ⚠️ Network Error Box #{cargo.index}: {e}")
    finally:
        cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue):
    log(log_q, f"[SHIPPER] 🚚 Provider: {CONFIG.PROVIDER.upper()}")
    
    async with aiohttp.ClientSession() as session:
        active_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            
            # Simple concurrent limiter (max 3 uploads at once to save memory)
            if len(active_shipments) >= 3:
                done, pending = await asyncio.wait(active_shipments, return_when=asyncio.FIRST_COMPLETED)
                active_shipments = list(pending)

            t = asyncio.create_task(ship_cargo(session, cargo, log_q))
            active_shipments.append(t)
            
        if active_shipments:
            log(log_q, f"[SHIPPER] ⏳ Finishing {len(active_shipments)} active shipments...")
            await asyncio.gather(*active_shipments)

# --- ENTRY POINT ---
async def run_fly_process(log_queue: asyncio.Queue, url: str, cookies: str, 
                          chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str):
    """Main Orchestrator called by FastAPI"""
    
    # Validation
    if not url:
        log(log_queue, "❌ Error: URL is missing")
        log_queue.put_nowait(None)
        return

    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    
    log(log_queue, "--- 🏭 LOGISTICS SYSTEM INITIALIZED ---")
    
    shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue))
    
    # Run heavy blocking process in executor
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            await loop.run_in_executor(
                pool, run_packager, loop, conveyor_belt, log_queue, 
                url, cookies, chunk_size, limit_rate, player_clients, wait_time, po_token
            )
        except Exception as e:
            log(log_queue, f"❌ Executor Error: {e}")
            await conveyor_belt.put(None)
        
    await shipper_task
    log(log_queue, "--- ✅ JOB COMPLETE ---")
    log_queue.put_nowait(None) # Signal end of stream
