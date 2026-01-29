import sys
import io
import os
import time
import asyncio
import subprocess
import threading
from typing import List
from .fly_structs import SessionContext, Cargo, CONFIG, CODEC_MAP, log_dispatch

# Import av conditionally
try:
    import av
except ImportError:
    pass

def miner_log_monitor(pipe, q, ctx: SessionContext):
    """Reads raw stderr from yt-dlp."""
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
    except ValueError:
        pass 

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

def run_packager(loop: asyncio.AbstractEventLoop, conveyor_belt: asyncio.Queue, log_q: asyncio.Queue, 
                 ctx: SessionContext,
                 target_url: str, chunk_size: str, limit_rate: str, 
                 player_clients: str, wait_time: str, po_token: str):
    
    # Ensure 'web' client is included correctly
    clients_list = [c.strip() for c in player_clients.split(',')] if player_clients else []
    if "web" not in clients_list:
        clients_list.append("web")
    final_clients = ",".join(clients_list)
    
    extractor_params = []
    if final_clients: extractor_params.append(f"player_client={final_clients}")
    if wait_time: extractor_params.append(f"playback_wait={wait_time}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    extractor_string = f"youtube:{';'.join(extractor_params)}" if extractor_params else ""

    cmd = [
        sys.executable, "-m", "yt_dlp", 
        "--newline", "-f", "ba", "-S", "+abr,+tbr,+size",
        "--http-chunk-size", chunk_size,
        "--limit-rate", limit_rate,
        "-o", "-"
    ]

    if os.path.exists(ctx.cookie_file): cmd.extend(["--cookies", ctx.cookie_file])
    if extractor_string: cmd.extend(["--extractor-args", extractor_string])
    cmd.append(target_url)

    printable_cmd = " ".join([f"'{c}'" if " " in c or ";" in c else c for c in cmd])
    log_dispatch(log_q, ctx, "status", text=f"[PACKAGER] 🏭 Starting: {target_url}")
    log_dispatch(log_q, ctx, "status", text=f"[COMMAND] {printable_cmd}")
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    log_thread = threading.Thread(target=miner_log_monitor, args=(process.stderr, log_q, ctx))
    log_thread.daemon = True
    log_thread.start()

    in_container = None

    try:
        if process.poll() is not None:
             raise Exception(f"Process finished unexpectedly code {process.returncode}")

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
            if curr_dur >= CONFIG.packaging_threshold:
                log_dispatch(log_q, ctx, "status", text=f"[PACKAGER] 🎁 Bin full ({curr_dur:.0f}s). Sealing Box #{box_id}...")
                
                mem_file, cutoff, size = create_package(buffer, in_stream, CONFIG.CHUNK_DURATION, out_fmt)
                
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

def run_format_listing(log_q, ctx, url, cookies_path, player_clients, po_token):
    log_dispatch(log_q, ctx, "status", text="--- 📋 LISTING FORMATS ---")
    
    cmd = [sys.executable, "-m", "yt_dlp", "--list-formats", "--newline"]
    
    if os.path.exists(cookies_path): 
        cmd.extend(["--cookies", cookies_path])
        
    clients_list = [c.strip() for c in player_clients.split(',')] if player_clients else []
    if "web" not in clients_list: clients_list.append("web")
    
    extractor_params = []
    if clients_list: extractor_params.append(f"player_client={','.join(clients_list)}")
    if po_token: extractor_params.append(f"po_token={po_token}")
    
    if extractor_params:
        cmd.extend(["--extractor-args", f"youtube:{';'.join(extractor_params)}"])
        
    cmd.append(url)
    
    log_dispatch(log_q, ctx, "status", text=f"[COMMAND] {' '.join(cmd)}")
    
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="ignore").strip()
            if text:
                log_dispatch(log_q, ctx, "status", text=text)
        proc.wait()
    except Exception as e:
        log_dispatch(log_q, ctx, "error", text=f"[LIST ERROR] {e}")