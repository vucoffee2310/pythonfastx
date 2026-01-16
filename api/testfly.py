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
    DEEPGRAM_KEY: str = "d6bf3bf38250b6370eKi424a0805f6ef915ae00bec"
    DEEPGRAMB/s` strongly suggests that the issue is **YouTube throttling**, not your_URL: str = "https://manage.deepgram.com/storage/assets"
    ASSEMBLYAI_KEY: str = "193053bc6ff84ba9aac246 Python code or pipe logic. YouTube aggressively throttles downloads that don't look like a real browser or that request data too quickly,5506f47d48"
    ASSEMBLYAI_URL: str = "https://api.assemblyai.com/v2/upload"
    
    COOKIE_FILE: str = "/ especially in datacenter IP ranges (like Vercel).

The `yt-dlp` parameters `chunk_sizetmp/cookies.txt"
    
    # Duration (seconds) before cutting a chunk
    CHUNK_DURATION:` and `limit_rate` are actually *causing* this when combined with YouTube's anti-bot protections. Request int = 1800
    # Overlap buffer (seconds)
    BUFFER_TAIL: int = 6ing large chunks often triggers throttling, and specifying a limit rate inside `yt-dlp` doesn't bypass server00

    @property
    def packaging_threshold(self) -> int:
        return self.CHUNK-side throttling.

Here is the strategy to fix this in `api/testfly.py`:

1.  _DURATION + self.BUFFER_TAIL

CONFIG = Config()
CODEC_MAP = {"opus": "**Remove `limit-rate` and `http-chunk-size`**: Let `yt-dlp` handle thewebm", "aac": "mp4", "mp3": "mp3", "vorbis": "ogg"}

class Cargo(NamedTuple):
    buffer: io.BytesIO
    index: int
    mime_ download strategy natively. Forcing these often flags the request.
2.  **Use `ios` client**: Thetype: str
    size_mb: float

# --- LOGGING HELPER ---
def log(q: `ios` client is currently the most resilient against throttling for audio streams.
3.  **Use `m4 asyncio.Queue, msg: str):
    if q: q.put_nowait(msg + "\n")

def miner_log_monitor(pipe, q):
    """Reads raw stderr from yt-dlpa` (aac) preference**: It often downloads faster and with less throttling than WebM/Opus on non-browser clients., filters spam, and pushes to queue."""
    last_progress_time = 0.0
    


Here is the corrected `api/testfly.py`.

```python
import sys
import io
import asyncio
    for line in iter(pipe.readline, b""):
        text = line.decode("utf-8import subprocess
import aiohttp
import threading
import os
import time
from typing import NamedTuple, List", errors="ignore").strip()
        if not text: continue

        if "[download]" in text:
            clean, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# Import av conditionally
_text = text.replace("[download]", "[MINER] ⛏️ ").strip()
            # Log progress every 1try:
    import av
except ImportError:
    pass 

# --- CONFIGURATION ---
@dataclass.5 seconds to reduce noise
            now = time.time()
            if (now - last_progress_time)(frozen=True)
class Config:
    PROVIDER: str = "assemblyai"
    # In production > 1.5:
                log(q, clean_text)
                last_progress_time =, use os.environ.get("DEEPGRAM_KEY")
    DEEPGRAM_KEY: str = now
        elif "[youtube]" in text:
            log(q, text.replace("[youtube]", "[MIN "d6bf3bf38250b6370e424a0805f6ef915ae00bec"
    DEEPGRAM_URL: str = "httpsER] 🔎 "))
        elif "[info]" in text:
            log(q, text.replace("[info]", "[MINER] ℹ️ "))
        else:
            log(q, text)

#://manage.deepgram.com/storage/assets"
    ASSEMBLYAI_KEY: str = " --- CPU BOUND ---
def create_package(packets: List, input_stream, max_dur: float,193053bc6ff84ba9aac2465506f47d48"
    ASSEMBLYAI_URL: str = "https://api.assemblyai.com fmt: str):
    output_mem = io.BytesIO()
    
    # strict='experimental' allows/v2/upload"
    
    COOKIE_FILE: str = "/tmp/cookies.txt"
 Opus in WebM/MP4 without erroring on some FFmpeg builds
    with av.open(output_mem, mode    
    # 30 minutes per chunk
    CHUNK_DURATION: int = 1800
    ="w", format=fmt, options={'strict': 'experimental'}) as container:
        stream = container.addBUFFER_TAIL: int = 600

    @property
    def packaging_threshold(self)_stream(input_stream.codec_context.name)
        stream.time_base = input_stream -> int:
        return self.CHUNK_DURATION + self.BUFFER_TAIL

CONFIG = Config()
CODEC_MAP = {"opus": "webm", "aac": "mp4", "mp3": "mp3", "vorbis": "ogg"}

class Cargo(NamedTuple):
    buffer: io.BytesIO
.time_base
        if input_stream.codec_context.extradata:
            stream.codec    index: int
    mime_type: str
    size_mb: float

# --- LOGGING HEL_context.extradata = input_stream.codec_context.extradata
            
        base_dts = packets[0].dts
        base_pts = packets[0].pts
        cutoff_idx = 0

        for i, pkt in enumerate(packets):
            rel_time = float(pktPER ---
def log(q: asyncio.Queue, msg: str):
    if q: q.put.dts - base_dts) * input_stream.time_base
            if rel_time <_nowait(msg + "\n")

def miner_log_monitor(pipe, q):
    """ max_dur:
                pkt.dts -= base_dts
                pkt.pts -= base_ptsReads raw stderr from yt-dlp, filters spam, and pushes to queue."""
    last_progress_time
                pkt.stream = stream
                container.mux(pkt)
                cutoff_idx = i
             = 0.0
    
    for line in iter(pipe.readline, b""):
        textelse:
                break
    output_mem.seek(0)
    size = round(output_mem = line.decode("utf-8", errors="ignore").strip()
        
        if not text: continue.getbuffer().nbytes / 1024 / 1024, 2)
    return output_mem, cutoff_idx, size

# --- PACKAGER ---
def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 

        if "[download]" in text:
            clean_text = text.replace("[download]", "[MINER] ⛏️ ").strip()
            # Log every 2 seconds to avoid spamming the UI
            now = time
                 target_url: str, cookies: str, 
                 chunk_size: str, limit_rate.time()
            if (now - last_progress_time) > 2.0:
                log: str, 
                 player_clients: str, wait_time: str, po_token: str):(q, clean_text)
                last_progress_time = now
                
        elif "[youtube]"
    
    # 1. Write Cookies
    if cookies:
        try:
            formatted_cookies in text:
            log(q, text.replace("[youtube]", "[MINER] 🔎 "))
         = cookies.replace(r"\n", "\n").replace(r"\t", "\t")
            withelif "[info]" in text:
            log(q, text.replace("[info]", "[MINER]  open(CONFIG.COOKIE_FILE, "w") as f:
                f.write(formatted_cookies)ℹ️ "))
        else:
            log(q, text)

# --- CPU BOUND ---
def create
            log(log_q, f"[SYSTEM] 🍪 Cookies processed to {CONFIG.COOKIE_FILE}")_package(packets: List, input_stream, max_dur: float, fmt: str):
    output
        except Exception as e:
            log(log_q, f"[ERROR] Failed to write cookies:_mem = io.BytesIO()
    
    # strict='experimental' allows muxing opus into webm or {e}")

    # 2. Extractor Args
    extractor_params = []
    if player_clients: extractor_params.append(f"player_client={player_clients}")
    if wait_time other combos
    with av.open(output_mem, mode="w", format=fmt, options={'strict': ': extractor_params.append(f"playback_wait={wait_time}")
    if po_token:experimental'}) as container:
        stream = container.add_stream(input_stream.codec_context.name extractor_params.append(f"po_token={po_token}")
    
    extractor_string =)
        stream.time_base = input_stream.time_base
        if input_stream.codec f"youtube:{';'.join(extractor_params)}" if extractor_params else ""

    # 3._context.extradata:
            stream.codec_context.extradata = input_stream.codec Build Command
    cmd = [
        sys.executable, "-m", "yt_dlp", 
_context.extradata
            
        base_dts = packets[0].dts
        base        "--newline",
        "-f", "ba/bestaudio", 
        "--http-chunk-size_pts = packets[0].pts
        cutoff_idx = 0

        for i, pkt in enumerate", chunk_size,
        "--limit-rate", limit_rate,
        "-o", "-"
    (packets):
            rel_time = float(pkt.dts - base_dts) * input_]

    if cookies: cmd.extend(["--cookies", CONFIG.COOKIE_FILE])
    if extractor_stream.time_base
            if rel_time < max_dur:
                pkt.dts -= base_dts
                pkt.pts -= base_pts
                pkt.stream = stream
                container.muxstring: cmd.extend(["--extractor-args", extractor_string])

    cmd.append(target_url)

    log(log_q, f"[PACKAGER] 🏭 Starting: {target_url}")
(pkt)
                cutoff_idx = i
            else:
                break
    output_mem.seek    log(log_q, f"[CONFIG] Chunk: {chunk_size} | Rate: {limit_(0)
    size = round(output_mem.getbuffer().nbytes / 1024 / 1024, 2)
    return output_mem, cutoff_idx, size

#rate}")
    
    # Use default buffering for Popen to rely on OS pipe behavior
    process = subprocess.Popen( --- PACKAGER ---
def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE
    ).Queue, log_q: asyncio.Queue, 
                 target_url: str, cookies: str,
    
    log_thread = threading.Thread(target=miner_log_monitor, args=(process. 
                 chunk_size: str, limit_rate: str, 
                 player_clients: str,stderr, log_q))
    log_thread.daemon = True
    log_thread.start()

 wait_time: str, po_token: str):
    
    # 1. Write Cookies
        log(log_q, "[PACKAGER] ⏳ Waiting for stream data...")

    try:
        if cookies:
        try:
            formatted_cookies = cookies.replace(r"\n", "\n").# --- CRITICAL FIX: BUFFFER DECOUPLING ---
        # Wrap the raw file descriptor in a BufferedReaderreplace(r"\t", "\t")
            with open(CONFIG.COOKIE_FILE, "w") as f:
                f.write(formatted_cookies)
            log(log_q, f"[SYSTEM] 🍪 Cookies processed to {CONFIG.COOKIE_FILE}")
        except Exception as e:
            log(log_q, f"[ERROR] Failed to write cookies: {e}")

    # 2. Extractor Args with a massive buffer (16MB).
        # This allows Python to suck 16MB out of the pipe immediately, freeing yt-dlp 
        # to continue downloading without blocking on the pipe.
        buffered_stdout = io.BufferedReader(process.stdout, buffer_size=16 * 1024 * 1024)

        # PyAV Options for low latency:
        # probesize: 32 bytes (minimal to detect
    extractor_params = []
    # If clients provided, use them; otherwise default to ios which is currently fast
    clients = player_clients if player_clients else "ios"
    extractor_params.append(f"player format)
        # analyzeduration: 0 (don't wait to calculate stream length)
        # fflags_client={clients}")
    
    # Important: Do not set playback_wait unless explicitly needed for PO Token: nobuffer (don't buffer internally in FFmpeg, we handled it in Python)
        av_options = {
            'probesize': '1024',
            'analyzeduration': '0',
             gen
    if wait_time and wait_time != "0": 
        extractor_params.append(f"playback_wait={wait_time}")
        
    if po_token: extractor_params.append'fflags': 'nobuffer',
            'strict': 'experimental'
        }

        in_container = av(f"po_token={po_token}")
    
    extractor_string = f"youtube:{';.open(buffered_stdout, mode="r", options=av_options)
        
        if not in'.join(extractor_params)}"

    # 3. Build Command
    # REMOVED: --limit-rate and_container.streams.audio:
            raise ValueError("No audio stream found")

        in_stream = in_container.streams.audio[0]
        codec = in_stream.codec_context.name
         --http-chunk-size as they trigger throttling
    # CHANGED: -f ba/bestaudio -> preferout_fmt = CODEC_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}"

        log(log_q, f"[PACKAGER] ✅ Stream Connected! Codec: { m4a for speed, fall back to bestaudio
    cmd = [
        sys.executable, "-m", "yt_dlp", 
        "--newline",
        "-f", "ba[ext=m4acodec}")

        buffer = []
        box_id = 0
        
        # Demuxing loop
        for]/ba", 
        "--concurrent-fragments", "4", # Parallel download parts if dash
        "-N packet in in_container.demux(in_stream):
            if packet.dts is None: continue", "4", # Number of threads
        "-o", "-"
    ]

    if cookies: cmd.extend(["--
            buffer.append(packet)
            
            if not buffer: continue

            # Check time delta
            curr_cookies", CONFIG.COOKIE_FILE])
    cmd.extend(["--extractor-args", extractor_string])
dur = float(packet.dts - buffer[0].dts) * in_stream.time_base    cmd.append(target_url)

    log(log_q, f"[PACKAGER] 🏭
            if curr_dur >= CONFIG.packaging_threshold:
                log(log_q, f"[PACK Starting: {target_url}")
    log(log_q, f"[CONFIG] Clients: {clients}AGER] 🎁 Sealing Box #{box_id} ({curr_dur:.0f}s)...")
                 | Threads: 4")
    
    # Large buffer to prevent pipe blocking
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        mem_file, cutoff, size = create_package(buffer, in_stream, CONFIG.CHUNK_DURATION, out_fmt)
                
                cargo = Cargo(mem_file, box_id, mime, size)bufsize=10 * 1024 * 1024 # 10MB Buffer
    )

                asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)    
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr
                buffer = buffer[cutoff + 1 :]
                box_id += 1

        if buffer:
            log(log_q, "[PACKAGER] 🏁 Stream ended. Sealing final box...")
            mem_, log_q))
    log_thread.daemon = True
    log_thread.start()

    file, _, size = create_package(buffer, in_stream, float("inf"), out_fmt)
log(log_q, "[PACKAGER] ⏳ Waiting for stream data...")

    try:
        #            cargo = Cargo(mem_file, box_id, mime, size)
            asyncio.run_ Fast open options for PyAV
        container_options = {
            'probesize': '32768coroutine_threadsafe(conveyor_belt.put(cargo), loop)

    except Exception as e:',      # 32KB is usually enough for audio
            'analyzeduration': '0',    # Start
        log(log_q, f"[PACKAGER ERROR] {e}")
    finally:
        if immediately
            'strict': 'experimental'
        }

        in_container = av.open(process.stdout process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout, mode="r", options=container_options)
        
        if not in_container.streams.audio=2)
            except subprocess.TimeoutExpired:
                process.kill()
        asyncio.run_:
            raise ValueError("No audio stream found")

        in_stream = in_container.streams.audiocoroutine_threadsafe(conveyor_belt.put(None), loop)

# --- SHIPPER ---
[0]
        codec = in_stream.codec_context.name
        out_fmt = CODECasync def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q: asyncio_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}".Queue):
    cargo.buffer.seek(0)
    if CONFIG.PROVIDER == "assemblyai":

        log(log_q, f"[PACKAGER] ✅ Stream Connected! Codec: {codec} |
        url = CONFIG.ASSEMBLYAI_URL
        headers = {"Authorization": CONFIG.ASSEMBLY Container: {out_fmt}")

        buffer = []
        box_id = 0

        for packetAI_KEY, "Content-Type": "application/octet-stream"}
    else:
        url = in in_container.demux(in_stream):
            if packet.dts is None: continue
 CONFIG.DEEPGRAM_URL
        headers = {"Authorization": f"Token {CONFIG.DEEPGRAM_            buffer.append(packet)
            
            # Use safe access for buffer elements
            if not buffer: continue

KEY}", "Content-Type": cargo.mime_type}

    try:
        # Increase upload timeout to 5            curr_dur = float(packet.dts - buffer[0].dts) * in_stream. minutes to handle large chunks
        async with session.post(url, headers=headers, data=cargo.buffertime_base
            if curr_dur >= CONFIG.packaging_threshold:
                log(log_q,, timeout=300) as resp:
            if resp.status >= 400:
                 f"[PACKAGER] 🎁 Bin full ({curr_dur:.0f}s). Sealing Box #{boxerr = await resp.text()
                log(log_q, f"[SHIPPER] ❌ Upload Failed_id}...")
                mem_file, cutoff, size = create_package(buffer, in_stream, Box #{cargo.index}: {resp.status} {err}")
                return
            
            body = await CONFIG.CHUNK_DURATION, out_fmt)
                
                cargo = Cargo(mem_file, box_ resp.json()
            res_id = body.get("upload_url") if CONFIG.PROVIDER == "id, mime, size)
                asyncio.run_coroutine_threadsafe(conveyor_belt.assemblyai" else (body.get("asset_id") or body.get("asset"))
            log(put(cargo), loop)
                buffer = buffer[cutoff + 1 :]
                box_id += log_q, f"[SHIPPER] ✅ Delivered Box #{cargo.index} | {cargo.size_mb}MB | Ref: {res_id}")
    except Exception as e:
        log(log_q1

        if buffer:
            log(log_q, "[PACKAGER] 🏁 Stream ended. Se, f"[SHIPPER] ⚠️ Error Box #{cargo.index}: {e}")
    finally:
        aling final box...")
            mem_file, _, size = create_package(buffer, in_stream, floatcargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log("inf"), out_fmt)
            cargo = Cargo(mem_file, box_id, mime, size_q: asyncio.Queue):
    log(log_q, f"[SHIPPER] 🚚 Logistics Partner)
            asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)

    except Exception as e:
        log(log_q, f"[PACKAGER ERROR] {e: {CONFIG.PROVIDER.upper()}")
    async with aiohttp.ClientSession() as session:
        }")
    finally:
        if process.poll() is None:
            process.terminate()
            tryactive_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            
            log(log_q, f"[SHIPPER] 🚚 Pick:
                process.wait(timeout=2)
            except:
                process.kill()
        asyncio.runed up Box #{cargo.index}. Shipping...")
            t = asyncio.create_task(ship_cargo(_coroutine_threadsafe(conveyor_belt.put(None), loop)

# --- SHIPPER ---session, cargo, log_q))
            active_shipments.append(t)
            # Prune completed tasks

async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, log_q:            active_shipments = [x for x in active_shipments if not x.done()]
            
 asyncio.Queue):
    cargo.buffer.seek(0)
    if CONFIG.PROVIDER == "assemblyai        if active_shipments:
            log(log_q, f"[SHIPPER] ⏳ Waiting for":
        url = CONFIG.ASSEMBLYAI_URL
        headers = {"Authorization": CONFIG.ASSEM {len(active_shipments)} active shipments...")
            await asyncio.gather(*active_shipments)

BLYAI_KEY, "Content-Type": "application/octet-stream"}
    else:
        url# --- ENTRY POINT ---
async def run_fly_process(log_queue: asyncio.Queue, url: = CONFIG.DEEPGRAM_URL
        headers = {"Authorization": f"Token {CONFIG.DEEPGRAM str, cookies: str, 
                          chunk_size: str, limit_rate: str, 
                          _KEY}", "Content-Type": cargo.mime_type}

    try:
        # Increase timeout forplayer_clients: str, wait_time: str, po_token: str):
    loop = asyncio.get large file uploads
        timeout = aiohttp.ClientTimeout(total=600) 
        async with_running_loop()
    conveyor_belt = asyncio.Queue()
    
    log(log_ session.post(url, headers=headers, data=cargo.buffer, timeout=timeout) as resp:
queue, "--- 🏭 LOGISTICS SYSTEM STARTED ---")
    
    shipper_task = asyncio.create            if resp.status >= 400:
                err = await resp.text()
                log(_task(run_shipper(conveyor_belt, log_queue))
    
    with ThreadPoollog_q, f"[SHIPPER] ❌ Upload Failed Box #{cargo.index}: {resp.status}Executor(max_workers=1) as pool:
        await loop.run_in_executor(
             {err}")
                return
            
            body = await resp.json()
            res_id = bodypool, run_packager, loop, conveyor_belt, log_queue, 
            url, cookies,.get("upload_url") if CONFIG.PROVIDER == "assemblyai" else (body.get("asset_ chunk_size, limit_rate, player_clients, wait_time, po_token
        )
        id") or body.get("asset"))
            log(log_q, f"[SHIPPER] ✅ Delivered
    await shipper_task
    log(log_queue, "--- ✅ ALL SHIPMENTS COMPLETE ---")
 Box #{cargo.index} | {cargo.size_mb}MB | Ref: {res_id}")
    log_queue.put_nowait(None)
