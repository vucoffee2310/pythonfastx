import sys
import io
import asyncio
import subprocess
import aiohttp
import threading
import os
import time
import json
import uuid
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
class JobConfig:
    provider: str
    deepgram_key: str
    assemblyai_key: str
    cookie_file: str
    
    # Constants
    deepgram_url: str = "https://manage.deepgram.com/storage/assets"
    assemblyai_url: str = "https://api.assemblyai.com/v2/upload"
    chunk_duration: int = 1800
    buffer_tail: int = 600

    @property
    def packaging_threshold(self) -> int:
        return self.chunk_duration + self.buffer_tail

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
                 player_clients: str, wait_time: str, po_token: str,
                 config: JobConfig):
    
    # 1. Write Cookies to unique file
    if cookies:
        try:
            formatted_cookies = cookies.replace(r"\n", "\n").replace(r"\t", "\t")
            with open(config.cookie_file, "w") as f:
                f.write(formatted_cookies)
            log(log_q, f"[SYSTEM] 🍪 Cookies processed to {config.cookie_file}")
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

    if cookies: cmd.extend(["--cookies", config.cookie_file])
    if extractor_string: cmd.extend(["--extractor-args", extractor_string])

    cmd.append(target_url)

    # Log command
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
            if curr_dur >= config.packaging_threshold:
                log(log_q, f"[PACKAGER] 🎁 Bin full ({curr_dur:.0f}s). Sealing Box #{box_id}...")
                mem_file, cutoff, size = create_package(buffer, in_stream, config.chunk_duration, out_fmt)
                
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
        # Cleanup
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
                log(log_q, "[CLEANUP] 🛑 Terminating downloader process...")
                process.terminate()
                try: process.wait(timeout=3)
                except: process.kill()
            else:
                 log(log_q, f"[CLEANUP] 🛑 Downloader exited with code {process.returncode}")

        # Signal end of queue
        asyncio.run_coroutine_threadsafe(conveyor_belt.put(None), loop)

# --- SHIPPER ---
async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q: asyncio.Queue, config: JobConfig):
    cargo.buffer.seek(0)
    
    # Generate Unique Asset Identity
    timestamp = int(time.time())
    ext = cargo.mime_type.split('/')[-1] if '/' in cargo.mime_type else 'bin'
    unique_filename = f"box_{cargo.index}_{timestamp}.{ext}"

    if config.provider == "assemblyai":
        url = config.assemblyai_url
        headers = {"Authorization": config.assemblyai_key, "Content-Type": "application/octet-stream"}
    else:
        # Deepgram Logic
        base_url = config.deepgram_url
        separator = "&" if "?" in base_url else "?"
        url = f"{base_url}{separator}name={unique_filename}"
        
        headers = {
            "Authorization": f"Token {config.deepgram_key}", 
            "Content-Type": cargo.mime_type
        }

    try:
        async with session.post(url, headers=headers, data=cargo.buffer) as resp:
            if resp.status >= 400:
                err = await resp.text()
                log(log_q, f"[SHIPPER] ❌ Upload Failed Box #{cargo.index}: {resp.status} {err}")
                return
            
            body = await resp.json()
            res_id = body.get("upload_url") if config.provider == "assemblyai" else (body.get("asset_id") or body.get("asset"))
            
            log(log_q, f"[SHIPPER] ✅ Delivered Box #{cargo.index} | {cargo.size_mb}MB | Asset: {unique_filename} | Ref: {res_id}")
            
            # Emit pure JSON log for the Extension to parse
            # The extension looks for `msg.asset`
            json_msg = {
                "index": cargo.index,
                "asset": res_id,
                "provider": config.provider,
                "size": cargo.size_mb,
                "filename": unique_filename
            }
            log(log_q, json.dumps(json_msg))

    except Exception as e:
        log(log_q, f"[SHIPPER] ⚠️ Error Box #{cargo.index}: {e}")
    finally:
        cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, config: JobConfig):
    log(log_q, f"[SHIPPER] 🚚 Logistics Partner: {config.provider.upper()}")
    async with aiohttp.ClientSession() as session:
        active_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            
            log(log_q, f"[SHIPPER] 🚚 Picked up Box #{cargo.index}. Shipping...")
            t = asyncio.create_task(ship_cargo(session, cargo, log_q, config))
            active_shipments.append(t)
            active_shipments = [x for x in active_shipments if not x.done()]
            
        if active_shipments:
            log(log_q, f"[SHIPPER] ⏳ Waiting for {len(active_shipments)} active shipments...")
            await asyncio.gather(*active_shipments)

# --- ENTRY POINT ---
async def run_fly_process(log_queue: asyncio.Queue, url: str, cookies: str, 
                          chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str,
                          provider: str, deepgram_key: str, assemblyai_key: str):
    """Main Orchestrator called by FastAPI"""
    
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    
    # Generate unique cookie path to support concurrency
    cookie_file = f"/tmp/cookies_{uuid.uuid4().hex}.txt"
    
    # Build Config
    config = JobConfig(
        provider=provider.lower() if provider else "assemblyai",
        deepgram_key=deepgram_key,
        assemblyai_key=assemblyai_key,
        cookie_file=cookie_file
    )
    
    log(log_queue, "--- 🏭 LOGISTICS SYSTEM STARTED ---")
    log(log_queue, f"[CONFIG] Provider: {config.provider} | Cookie File: {cookie_file}")
    
    shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue, config))
    
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool, run_packager, loop, conveyor_belt, log_queue, 
                url, cookies, chunk_size, limit_rate, player_clients, wait_time, po_token, config
            )
    except Exception as e:
        log(log_queue, f"[SYSTEM ERROR] {e}")
    finally:
        await shipper_task
        # Clean up cookies
        if os.path.exists(config.cookie_file):
            try:
                os.remove(config.cookie_file)
                log(log_queue, "[CLEANUP] 🍪 Temporary cookie file deleted.")
            except: pass
            
    log(log_queue, "--- ✅ ALL SHIPMENTS COMPLETE ---")
    log_queue.put_nowait(None) # Signal end of stream
