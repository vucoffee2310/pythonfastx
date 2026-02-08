import sys
import io
import os
import time
import math
import asyncio
import subprocess
import threading
import uuid
import aiohttp
from typing import List
from concurrent.futures import ThreadPoolExecutor
from .core import SessionContext, Cargo, CONFIG, CODEC_MAP, log_dispatch

try:
    import av
except ImportError:
    pass

def miner_log_monitor(pipe, q, ctx: SessionContext):
    if ctx.mode == "data":
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
                    clean_text = text.replace("[download]", "⛏️").strip()
                    log_dispatch(q, ctx, "status", text=clean_text)
                    last_progress_time = now
            elif "error" in text.lower():
                log_dispatch(q, ctx, "error", text=f"[MINER ERROR] {text}")
            else:
                log_dispatch(q, ctx, "status", text=f"[MINER] {text}")
    except ValueError: pass 

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
    size = round(output_mem.getbuffer().nbytes / 1024 / 1024, 2)
    return output_mem, cutoff_idx, size

def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                 ctx: SessionContext, target_url: str, chunk_size: str, limit_rate: str, 
                 player_clients: str, wait_time: str, po_token: str, impersonate: str, 
                 no_playlist: bool, total_duration: float = 0.0, split_duration: int = 30):
    
    clients_list = [c.strip() for c in player_clients.split(',')] if player_clients else []
    if "web" not in clients_list: clients_list.append("web")
    
    extractor_params = []
    if clients_list: extractor_params.append(f"player_client={','.join(clients_list)}")
    if wait_time: extractor_params.append(f"playback_wait={wait_time}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    extractor_string = f"youtube:{';'.join(extractor_params)}" if extractor_params else ""

    cmd = [
        sys.executable, "-m", "yt_dlp", "--newline", "-f", "ba", "-S", "+abr,+tbr,+size",
        "--http-chunk-size", chunk_size, "--limit-rate", limit_rate, "-o", "-"
    ]
    if no_playlist: cmd.append("--no-playlist")
    if os.path.exists(ctx.cookie_file): cmd.extend(["--cookies", ctx.cookie_file])
    if extractor_string: cmd.extend(["--extractor-args", extractor_string])
    if impersonate: cmd.extend(["--impersonate", impersonate])
    cmd.append(target_url)

    # --- DUAL MODE SPLIT LOGIC ---
    
    # 1. Base Target
    base_split_seconds = split_duration * 60
    target_split = base_split_seconds
    threshold = base_split_seconds + CONFIG.BUFFER_TAIL # e.g. 30m + 10m buffer = 40m before cut

    # 2. Balanced (New) Approach: Use Total Duration to split evenly if possible
    if total_duration > 0:
        num_parts = math.ceil(total_duration / base_split_seconds)
        if num_parts > 0:
            target_split = total_duration / num_parts
            # With balanced split, we rely on even division, so the buffer is minimal (30s)
            threshold = target_split + 30.0 
            log_dispatch(log_q, ctx, "status", text=f"[PACKAGER] ⚖️ Balanced Split: {num_parts} parts @ ~{target_split/60:.1f}m each (Total: {total_duration/60:.1f}m)")

    log_dispatch(log_q, ctx, "status", text=f"[PACKAGER] factory start: {target_url}")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q, ctx))
    log_thread.daemon = True
    log_thread.start()

    in_container = None
    try:
        if process.poll() is not None: raise Exception(f"Process finished unexpectedly code {process.returncode}")
        in_container = av.open(process.stdout, mode="r")
        in_stream = in_container.streams.audio[0]
        codec = in_stream.codec_context.name
        out_fmt = CODEC_MAP.get(codec, "matroska")
        mime = f"audio/{out_fmt}"
        log_dispatch(log_q, ctx, "status", text=f"[PACKAGER] ✅ Connected: {codec}/{out_fmt}")

        buffer = []
        box_id = 0
        for packet in in_container.demux(in_stream):
            if packet.dts is None: continue
            buffer.append(packet)
            curr_dur = float(packet.dts - buffer[0].dts) * in_stream.time_base
            
            # Use calculated threshold (Dual Mode)
            if curr_dur >= threshold:
                log_dispatch(log_q, ctx, "status", text=f"[PACKAGER] 🎁 Bin full ({curr_dur:.0f}s). Sealing Box #{box_id}...")
                mem_file, cutoff, size = create_package(buffer, in_stream, target_split, out_fmt)
                cargo = Cargo(mem_file, box_id, mime, size)
                asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)
                buffer = buffer[cutoff + 1 :]
                box_id += 1

        if buffer:
            log_dispatch(log_q, ctx, "status", text="[PACKAGER] 🏁 Stream ended. Sealing final box...")
            mem_file, _, size = create_package(buffer, in_stream, float("inf"), out_fmt)
            cargo = Cargo(mem_file, box_id, mime, size)
            asyncio.run_coroutine_threadsafe(conveyor_belt.put(cargo), loop)
    except Exception as e:
        log_dispatch(log_q, ctx, "error", text=f"[PACKAGER ERROR] 💥 {e}")
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

def run_format_listing(log_q, ctx, url, cookies_path, player_clients, po_token, impersonate, no_playlist: bool):
    log_dispatch(log_q, ctx, "status", text="--- 📋 LISTING FORMATS ---")
    cmd = [sys.executable, "-m", "yt_dlp", "--list-formats", "--newline"]
    if no_playlist: cmd.append("--no-playlist")
    if os.path.exists(cookies_path): cmd.extend(["--cookies", cookies_path])
    
    clients_list = [c.strip() for c in player_clients.split(',')] if player_clients else []
    if "web" not in clients_list: clients_list.append("web")
    
    extractor_params = []
    if clients_list: extractor_params.append(f"player_client={','.join(clients_list)}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    if extractor_params: cmd.extend(["--extractor-args", f"youtube:{';'.join(extractor_params)}"])
    if impersonate: cmd.extend(["--impersonate", impersonate])
    
    cmd.append(url)
    log_dispatch(log_q, ctx, "status", text=f"[COMMAND] {' '.join(cmd)}")
    
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            if text: log_dispatch(log_q, ctx, "status", text=text)
        proc.wait()
    except Exception as e: log_dispatch(log_q, ctx, "error", text=f"[LIST ERROR] {e}")

async def ship_cargo(session: aiohttp.ClientSession, cargo: Cargo, ctx: SessionContext, log_q: asyncio.Queue):
    cargo.buffer.seek(0)
    url, headers = "", {}
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
                log_dispatch(log_q, ctx, "error", text=f"[SHIPPER] ❌ Upload Failed Box #{cargo.index}: {resp.status} {err}", payload={"error_code": resp.status, "details": err, "box": cargo.index})
                return
            body = await resp.json()
            asset_url = body.get("upload_url", "") if ctx.provider == "assemblyai" else f"https://manage.deepgram.com/storage/assets/{body.get('asset_id') or body.get('asset') or body.get('id') or 'unknown'}"
            log_dispatch(log_q, ctx, "asset", text=f"[SHIPPER] ✅ Delivered Box #{cargo.index} | {cargo.size_mb}MB", payload={"index": cargo.index, "asset": asset_url, "provider": ctx.provider, "size_mb": cargo.size_mb})
    except Exception as e:
        log_dispatch(log_q, ctx, "error", text=f"[SHIPPER ERROR] {e}", payload={"details": str(e)})
    finally: cargo.buffer.close()

async def run_shipper(conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, ctx: SessionContext):
    log_dispatch(log_q, ctx, "status", text=f"[SHIPPER] 🚚 Logistics Partner: {ctx.provider.upper()}")
    async with aiohttp.ClientSession() as session:
        active_shipments = []
        while True:
            cargo = await conveyor_belt.get()
            if cargo is None: break
            log_dispatch(log_q, ctx, "status", text=f"[SHIPPER] 🚚 Picked up Box #{cargo.index}. Shipping...")
            t = asyncio.create_task(ship_cargo(session, cargo, ctx, log_q))
            active_shipments.append(t)
            active_shipments = [x for x in active_shipments if not x.done()]
        if active_shipments:
            log_dispatch(log_q, ctx, "status", text=f"[SHIPPER] ⏳ Waiting for {len(active_shipments)} active shipments...")
            await asyncio.gather(*active_shipments)

async def heartbeat(q: asyncio.Queue):
    while True:
        await asyncio.sleep(5)
        log_dispatch(q, SessionContext("","","","debug",""), "keepalive")

async def run_fly_process(log_queue: asyncio.Queue, url: str, cookies: str, chunk_size: str, limit_rate: str, 
                          player_clients: str, wait_time: str, po_token: str, impersonate: str, provider: str, mode: str, 
                          dg_key: str, aai_key: str, only_list_formats: bool = False, no_playlist: bool = False,
                          total_duration: float = 0.0, split_duration: int = 30):
    loop = asyncio.get_running_loop()
    conveyor_belt = asyncio.Queue()
    cookie_filename = f"/tmp/cookies_{uuid.uuid4().hex[:8]}.txt"
    if cookies:
        try:
            with open(cookie_filename, "w") as f: f.write(cookies.replace(r"\n", "\n").replace(r"\t", "\t"))
        except: pass

    ctx = SessionContext(provider.lower(), dg_key or os.environ.get("DEEPGRAM_KEY", ""), aai_key or os.environ.get("ASSEMBLYAI_KEY", ""), mode.lower(), cookie_filename)
    log_dispatch(log_queue, ctx, "status", text="--- 🏭 LOGISTICS SYSTEM STARTED ---")
    hb_task = asyncio.create_task(heartbeat(log_queue))
    
    with ThreadPoolExecutor(max_workers=1) as pool:
        if only_list_formats:
            await loop.run_in_executor(pool, run_format_listing, log_queue, ctx, url, cookie_filename, player_clients, po_token, impersonate, no_playlist)
            log_dispatch(log_queue, ctx, "status", text="--- ✅ DONE ---")
        else:
            shipper_task = asyncio.create_task(run_shipper(conveyor_belt, log_queue, ctx))
            await loop.run_in_executor(pool, run_packager, loop, conveyor_belt, log_queue, ctx, url, chunk_size, limit_rate, player_clients, wait_time, po_token, impersonate, no_playlist, total_duration, split_duration)
            await shipper_task
            log_dispatch(log_queue, ctx, "status", text="--- ✅ ALL SHIPMENTS COMPLETE ---")
    
    hb_task.cancel()
    if os.path.exists(cookie_filename): os.remove(cookie_filename)
    log_queue.put_nowait(None)
