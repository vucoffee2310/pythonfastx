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

# --- PROTOCOL: LOG DISPATCHER ---
def log_dispatch(q: asyncio.Queue, ctx: SessionContext, event_type: str, payload: dict = None, text: str = None):
    """
    Standardized Protocol Emitter.
    protocol format: { "type": "asset"|"status"|"error", "payload": { ... } }
    """
    if not q: return

    # Construct the standard protocol packet
    packet_obj = {
        "type": event_type,
        "payload": payload or {}
    }
    json_packet = json.dumps(packet_obj)

    # 1. DATA MODE (Strict)
    if ctx.mode == "data":
        # Only emit functional events that the extension logic relies on.
        # "asset": Contains the final URL.
        # "error": Contains critical failure info.
        if event_type in ["asset", "error"]:
            q.put_nowait(json_packet + "\n")
        return

    # 2. DEBUG MODE (Verbose)
    # Output human-readable text logs first
    if text:
        q.put_nowait(f"[{event_type.upper()}] {text}\n")
    
    # Output the JSON protocol packet (so the extension can still parse it if it wants)
    q.put_nowait(json_packet + "\n")

def miner_log_monitor(pipe, q, ctx: SessionContext):
    """Reads raw stderr from yt-dlp."""
    if ctx.mode == "data":
        # Consume pipe silently
        for _ in iter(pipe.readline, b""): pass
        return

    last_progress_time = 0.0
    try:
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            if not text: continue

            if "[download]" in text:
                now = time.time()
                if (now - last_progress_time) > 1.0:
                    clean = text.replace("[download]", "⛏️").strip()
                    log_dispatch(q, ctx, "status", payload={"status": "downloading", "msg": clean}, text=clean)
                    last_progress_time = now
            elif "error" in text.lower():
                log_dispatch(q, ctx, "error", payload={"msg": text}, text=text)
            else:
                log_dispatch(q, ctx, "status", payload={"status": "info", "msg": text}, text=text)
    except ValueError: pass 

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
                pkt.dts -= base_dts; pkt.pts -= base_pts; pkt.stream = stream
                container.mux(pkt)
                cutoff_idx = i
            else: break
    output_mem.seek(0)
    size = round(output_mem.getbuffer().nbytes / 1024 / 1024, 2)
    return output_mem, cutoff_idx, size

# --- PACKAGER ---
def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                 ctx: SessionContext, target_url: str, chunk_size: str, limit_rate: str, 
                 player_clients: str, wait_time: str, po_token: str):
    
    extractor_params = []
    if player_clients: extractor_params.append(f"player_client={player_clients}")
    if wait_time: extractor_params.append(f"playback_wait={wait_time}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    extractor_string = f"youtube:{';'.join(extractor_params)}" if extractor_params else ""

    cmd = [sys.executable, "-m", "yt_dlp", "--newline", "-f", "ba", "-S", "+abr,+tbr,+size",
        "--http-chunk-size", chunk_size, "--limit-rate", limit_rate, "-o", "-"]
    if os.path.exists(ctx.cookie_file): cmd.extend(["--cookies", ctx.cookie_file])
    if extractor_string: cmd.extend(["--extractor-args", extractor_string])
    cmd.append(target_url)

    printable_cmd = " ".join([f"'{c}'" if " " in c or ";" in c else c for c in cmd])
    log_dispatch(log_q, ctx, "status", text=f"Starting Stream: {target_url}")
    log_dispatch(log_q, ctx, "debug", text=f"Command: {printable_cmd}")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q, ctx))
    log_thread.daemon = True; log_thread.start()

    in_container = None
    try:
        if process.poll() is not None: raise Exception(f"Process finished code {process.returncode}")
        in_container = av.open(process.stdout, mode="r")
        in_stream = in_container.streams.audio[0]
        codec = in_stream.codec_context.name
        out_fmt = CODEC_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}"

        log_dispatch(log_q, ctx, "status", text=f"Connected: {codec}/{out_fmt}")
        buffer = []; box_id = 0

        for packet in in_container.demux(in_stream):
            if packet.dts is None: continue
            buffer.append(packet)
            curr_dur = float(packet.dts - buffer[0].dts) * in_stream.time_base
            
            if curr_dur >= CONFIG.packaging_threshold:
                log_dispatch(log_q, ctx, "status", text=f"Bin full ({curr_dur:.0f}s). Sealing Box #{box_id}...")
                mem_file, cutoff, size = create_package(buffer, in_stream, CONFIG.CHUNK_DURATION, out_fmt)
                cargo = Cargo(mem_file, box_id, mime, size)
                asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)
                buffer = buffer[cutoff + 1 :]; box_id += 1

        if buffer:
            log_dispatch(log_q, ctx, "status", text="Stream ended. Sealing final box...")
            mem_file, _, size = create_package(buffer, in_stream, float("inf"), out_fmt)
            cargo = Cargo(mem_file, box_id, mime, size)
            asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)

    except Exception as e:
        log_dispatch(log_q, ctx, "error", payload={"msg": str(e)}, text=f"Packager Error: {e}")
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
async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, ctx: SessionContext, log_q: asyncio.Queue):
    cargo.buffer.seek(0)
    url = ""
    headers = {}
    
    if ctx.provider == "assemblyai":
        url = "https://api.assemblyai.com/v2/upload"
        headers = { "Authorization": ctx.assemblyai_key, "Content-Type": "application/octet-stream" }
    elif ctx.provider == "deepgram":
        url = "https://manage.deepgram.com/storage/assets"
        headers = { "Authorization": f"Token {ctx.deepgram_key}", "Content-Type": cargo.mime_type }

    try:
        async with session.post(url, headers=headers, data=cargo.buffer) as resp:
            if resp.status >= 400:
                err = await resp.text()
                log_dispatch(log_q, ctx, "error", 
                    payload={"msg": f"Upload failed {resp.status}", "details": err, "box": cargo.index}, 
                    text=f"Upload Failed Box #{cargo.index}: {resp.status} {err}")
                return
            
            body = await resp.json()
            asset_url = ""
            
            if ctx.provider == "assemblyai":
                asset_url = body.get("upload_url", "")
            elif ctx.provider == "deepgram":
                res_id = body.get("asset_id") or body.get("asset") or body.get("id") or "unknown"
                asset_url = f"https://manage.deepgram.com/storage/assets/{res_id}"

            # Emit ASSET event
            success_payload = {
                "index": cargo.index,
                "asset": asset_url,
                "provider": ctx.provider,
                "size_mb": cargo.size_mb
            }
            log_dispatch(log_q, ctx, "asset", payload=success_payload, text=f"Delivered Box #{cargo.index} | {cargo.size_mb}MB")

    except Exception as e:
        log_dispatch(log_q, ctx, "error", payload={"msg": str(e)}, text=f"Shipper Error: {e}")
    finally:
        cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, ctx: SessionContext):
    log_dispatch(log_q, ctx, "status", text=f"Logistics Partner: {ctx.provider.upper()}")
    
    async with aiohttp.ClientSession() as session:
        active_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            
            log_dispatch(log_q, ctx, "status", text=f"Picked up Box #{cargo.index}. Shipping...")
            t = asyncio.create_task(ship_cargo(session, cargo, ctx, log_q))
            active_shipments.append(t)
            active_shipments = [x for x in active_shipments if not x.done()]
            
        if active_shipments:
            log_dispatch(log_q, ctx, "status", text=f"Waiting for {len(active_shipments)} active shipments...")
            await asyncio.gather(*active_shipments)

# --- ENTRY POINT ---
async def run_fly_process(log_queue: asyncio.Queue, 
                          url: str, cookies: str, 
                          chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str,
                          provider: str, mode: str, dg_key: str, aai_key: str):
    
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    
    # Cookie File (Temp)
    cookie_filename = f"/tmp/cookies_{uuid.uuid4().hex[:8]}.txt"
    if cookies:
        try:
            formatted_cookies = cookies.replace(r"\n", "\n").replace(r"\t", "\t")
            with open(cookie_filename, "w") as f: f.write(formatted_cookies)
        except Exception: pass

    # Environment Variable Fallback
    final_dg_key = dg_key if dg_key else os.environ.get("DEEPGRAM_KEY", "")
    final_aai_key = aai_key if aai_key else os.environ.get("ASSEMBLYAI_KEY", "")

    ctx = SessionContext(
        provider=provider.lower(),
        deepgram_key=final_dg_key,
        assemblyai_key=final_aai_key,
        mode=mode.lower(),
        cookie_file=cookie_filename
    )
    
    log_dispatch(log_queue, ctx, "status", text="--- LOGISTICS SYSTEM STARTED ---")
    
    shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue, ctx))
    
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(
            pool, run_packager, loop, conveyor_belt, log_queue, 
            ctx, url, chunk_size, limit_rate, player_clients, wait_time, po_token
        )
        
    await shipper_task
    
    if os.path.exists(cookie_filename): os.remove(cookie_filename)
    log_dispatch(log_queue, ctx, "status", text="--- ALL SHIPMENTS COMPLETE ---")
    log_queue.put_nowait(None)
