from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import subprocess
import asyncio
from typing import Optional
from . import core
from . import engine

# ========================================================
# 1. SETUP & ENVIRONMENT
# ========================================================
core.setup_environment()

av_status = "Initializing..."
try:
    import av
    av_status = f"✅ PyAV {av.__version__} | Codecs: {len(av.codecs_available)}"
except Exception as e:
    av_status = f"❌ PyAV Error: {e}"

app = FastAPI()

# Mount Static Files (CSS, JS)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================================================
# 2. UI ROUTE
# ========================================================
@app.get("/", response_class=HTMLResponse)
def index():
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if not os.path.exists(index_path): return HTMLResponse("<h1>Error: static/index.html not found</h1>", status_code=500)
    with open(index_path, "r", encoding="utf-8") as f: content = f.read()
    
    config_script = f"""<script>window.SERVER_CONFIG = {{ "projectRoot": "{core.paths['root']}" }};</script>"""
    final_html = content.replace('<script src="/static/app.js"></script>', f'{config_script}\n<script src="/static/app.js"></script>')
    return HTMLResponse(content=final_html)

# ========================================================
# 3. API ENDPOINTS
# ========================================================
class FlyRequest(BaseModel):
    url: str
    cookies: str
    chunk_size: str = "8M"
    limit_rate: str = "4M"
    wait_time: str = "2"
    player_clients: str = "tv,android,ios,web"
    po_token: str = ""
    impersonate: str = ""
    provider: str = "assemblyai"
    mode: str = "debug"
    deepgram_key: Optional[str] = ""
    assemblyai_key: Optional[str] = ""
    only_list_formats: bool = False
    no_playlist: bool = False

@app.post("/api/fly")
async def fly_process(payload: FlyRequest):
    q = asyncio.Queue()
    asyncio.create_task(engine.run_fly_process(
        log_queue=q, url=payload.url, cookies=payload.cookies, chunk_size=payload.chunk_size,
        limit_rate=payload.limit_rate, player_clients=payload.player_clients, wait_time=payload.wait_time,
        po_token=payload.po_token, impersonate=payload.impersonate, provider=payload.provider, mode=payload.mode,
        dg_key=payload.deepgram_key, aai_key=payload.assemblyai_key, only_list_formats=payload.only_list_formats,
        no_playlist=payload.no_playlist
    ))
    
    async def log_generator():
        while True:
            data = await q.get()
            if data is None: break
            yield data
    return StreamingResponse(log_generator(), media_type="text/plain")

@app.get("/api/list")
def list_files(path: str = "/", source: str = "runtime"):
    if source == "runtime": path = os.path.abspath(path)
    if source == "build":
        lookup_path = path.rstrip('/') if len(path) > 1 and path.endswith('/') else path
        items = core.BUILD_FS_CACHE.get(lookup_path, [])
        return {"current_path": path, "items": items, "source": "build"}

    if not os.path.exists(path): raise HTTPException(404, "Path not found")
    items = []
    try:
        with os.scandir(path) as entries:
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    items.append({
                        "name": e.name, "path": e.path, "is_dir": e.is_dir(),
                        "size": core.get_size_str(e.path) if not e.is_dir() else "-",
                        "ext": os.path.splitext(e.name)[1].lower() if not e.is_dir() else ""
                    })
                except: continue
        return {"current_path": path, "items": items, "source": "runtime"}
    except Exception as e: raise HTTPException(403, str(e))

@app.get("/api/shell")
def run_shell(cmd: str):
    if not cmd: return {"out": ""}
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10, cwd=core.paths["root"], env=os.environ)
        return {"out": res.stdout}
    except subprocess.TimeoutExpired: return {"out": "⚠️ Command timed out."}
    except Exception as e: return {"out": str(e)}

@app.get("/api/stats")
def stats_endpoint():
    stats = []
    locations = [("App Code", core.paths["root"]), ("Dependencies", core.paths["vendor"]), ("Binaries", core.paths["bin"]), ("Temp", "/tmp")]
    for label, path in locations:
        if os.path.exists(path): stats.append({"label": label, "path": path, "size": core.get_size_str(path)})
    return {
        "storage": stats, "av": av_status, "runtime": core.get_runtime_env_info(),
        "tools": core.compare_tools(), "inodes": core.get_python_inodes(), "has_build_index": bool(core.BUILD_FS_CACHE)
    }

@app.get("/api/view")
def view_file(path: str):
    if not os.path.exists(path): return {"error": "File not found"}
    try:
        if os.path.getsize(path) > 500_000: return {"error": "File too large"}
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary file"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f: return {"content": f.read()}
    except Exception as e: return {"error": str(e)}

@app.get("/api/delete")
def delete_file(path: str):
    try:
        if os.path.isdir(path): os.rmdir(path)
        else: os.remove(path)
        return {"ok": True}
    except Exception as e: return {"error": str(e)}

@app.get("/api/download")
def download(path: str):
    if os.path.exists(path): return FileResponse(path, filename=os.path.basename(path))
