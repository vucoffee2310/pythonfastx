import sys
import io
import asyncio
import subprocess
import aiohttp
import threading
import os
import time
import json
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
    # URL Constants
    DEEPGRAM_URL: str = "https://manage.deepgram.com/storage/assets"
    ASSEMBLYAI_URL: str = "https://api.assemblyai.com/v2/upload"
    
    COOKIE_FILE: str = "/tmp/cookies.txt"
    
    # Muxing Settings
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
                clean_text = text.replace("[download]", "[MINER] ⛏️ ").strip()
                now = time.time()
                if (now - last_progress_time) > 1.0: # Reduce log spam
                    log(q, clean_text)
                    last_progress_time = now
            elif "[youtube]" in text:
                log(q, text.replace("[youtube]", "[MINER] 🔎 "))
            elif "[info]" in text:
                log(q, text.replace("[info]", "[MINER] ℹ️ "))
            elif "error" in text.lower():
                log(q, f"[MINER ERROR] {text}")
    except ValueError:
        pass 

# --- CPU BOUND ---
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
    
    log(log_q, f"[PACKAGER] 🏭 Starting Stream...")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q))
    log_thread.daemon = True
    log_thread.start()

    in_container = None

    try:
        if process.poll() is not None:
             raise Exception(f"Process finished unexpectedly with code {process.returncode}")

        in_container = av.open(process.stdout, mode="r")
        in_stream = in_container.streams.audio[0]
        codec = in_stream.codec_context.name
        out_fmt = CODEC_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}"

        log(log_q, f"[PACKAGER] ✅ Stream Connected! Codec: {codec}")

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
        if in_container:
            try: in_container.close()
            except: pass
        
        if process:
            if process.stdout: process.stdout.close()
            if process.stderr: process.stderr.close()
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=3)
                except: process.kill()

        asyncio.run_coroutine_threadsafe(conveyor_belt.put(None), loop)

# --- SHIPPER ---
async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q: asyncio.Queue, 
                     provider: str, mode: str, dg_key: str, aai_key: str):
    
    cargo.buffer.seek(0)
    
    # Unique Filename Logic
    timestamp = int(time.time())
    ext = cargo.mime_type.split('/')[-1] if '/' in cargo.mime_type else 'bin'
    filename = f"box_{cargo.index}_{timestamp}.{ext}"

    target_url = ""
    headers = {}
    
    # Configure Provider Specifics
    if provider == "assemblyai":
        target_url = CONFIG.ASSEMBLYAI_URL
        headers = {
            "Authorization": aai_key, 
            "Content-Type": "application/octet-stream"
        }
    else: # Deepgram
        # We append the name query parameter to help with unique identification in storage
        base_url = CONFIG.DEEPGRAM_URL
        sep = "&" if "?" in base_url else "?"
        target_url = f"{base_url}{sep}name={filename}"
        headers = {
            "Authorization": f"Token {dg_key}", 
            "Content-Type": cargo.mime_type
        }

    try:
        # If in debug mode, maybe we don't upload? 
        # For now, we assume 'debug' just means detailed extension logs, 
        # but the backend still performs the action.
        
        async with session.post(target_url, headers=headers, data=cargo.buffer) as resp:
            if resp.status >= 400:
                err = await resp.text()
                log(log_q, f"[SHIPPER] ❌ Upload Failed Box #{cargo.index}: {resp.status} {err}")
                return
            
            body = await resp.json()
            
            # FORMAT ASSET URL ACCORDING TO REQUIREMENTS
            asset_url = ""
            
            if provider == "assemblyai":
                # Expects: https://cdn.assemblyai.com/upload/...
                asset_url = body.get("upload_url", "")
            else: # Deepgram
                # Expects: https://manage.deepgram.com/storage/assets + responsed data
                # Deepgram storage API usually returns an asset_id or similar. 
                # We concatenate the base storage URL with the returned ID/Path.
                
                # Try finding likely ID keys
                asset_id = body.get("asset_id") or body.get("asset") or body.get("id")
                
                # Fallback if the API returns a full URL already (unlikely for storage API)
                if body.get("url"): 
                     asset_url = body.get("url")
                elif asset_id:
                     # Remove query params from base config for clean path
                     clean_base = CONFIG.DEEPGRAM_URL.split('?')[0].rstrip('/')
                     asset_url = f"{clean_base}/{asset_id}"
                else:
                    # Last resort: dump the whole JSON as string if we can't parse it
                    asset_url = f"RAW_JSON:{json.dumps(body)}"

            # Send JSON structure expected by the Extension's popup.js
            response_msg = json.dumps({
                "asset": asset_url,
                "index": cargo.index,
                "provider": provider
            })
            
            # The extension looks for this JSON line
            log(log_q, response_msg)
            log(log_q, f"[SHIPPER] ✅ Delivered Box #{cargo.index} | {cargo.size_mb}MB")

    except Exception as e:
        log(log_q, f"[SHIPPER] ⚠️ Error Box #{cargo.index}: {e}")
    finally:
        cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                      provider: str, mode: str, dg_key: str, aai_key: str):
    
    log(log_q, f"[SHIPPER] 🚚 Logistics Partner: {provider.upper()}")
    
    if provider == "deepgram" and not dg_key:
         log(log_q, "[SHIPPER] ❌ Missing Deepgram API Key")
         return
    if provider == "assemblyai" and not aai_key:
         log(log_q, "[SHIPPER] ❌ Missing AssemblyAI API Key")
         return

    async with aiohttp.ClientSession() as session:
        active_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            
            log(log_q, f"[SHIPPER] 🚚 Picked up Box #{cargo.index}. Shipping...")
            t = asyncio.create_task(ship_cargo(session, cargo, log_q, provider, mode, dg_key, aai_key))
            active_shipments.append(t)
            active_shipments = [x for x in active_shipments if not x.done()]
            
        if active_shipments:
            log(log_q, f"[SHIPPER] ⏳ Waiting for {len(active_shipments)} active shipments...")
            await asyncio.gather(*active_shipments)

# --- ENTRY POINT ---
async def run_fly_process(log_queue: asyncio.Queue, 
                          url: str, cookies: str, 
                          chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str,
                          provider: str, mode: str, dg_key: str, aai_key: str):
    """Main Orchestrator called by FastAPI"""
    
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    
    log(log_queue, "--- 🏭 LOGISTICS SYSTEM STARTED ---")
    log(log_queue, f"Target: {provider.upper()} | Mode: {mode.upper()}")
    
    # Shipper runs in background, waiting for chunks
    shipper_task = asyncio.create_task(run_shipper(
        conveyor_belt, log_queue, provider, mode, dg_key, aai_key
    ))
    
    # Packager runs in a thread pool (CPU bound av/yt-dlp)
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(
            pool, run_packager, loop, conveyor_belt, log_queue, 
            url, cookies, chunk_size, limit_rate, player_clients, wait_time, po_token
        )
        
    await shipper_task
    log(log_queue, "--- ✅ ALL SHIPMENTS COMPLETE ---")
    log_queue.put_nowait(None)
