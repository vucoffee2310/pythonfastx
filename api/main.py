from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import sys
import subprocess
import asyncio
import platform
import shutil
import json
from typing import Optional, Dict, List
from . import testfly

# ========================================================
# 1. SETUP & PATH CONFIGURATION
# ========================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = "/var/task" if os.path.exists("/var/task") else os.getcwd()

paths = {
    "root": project_root,
    "vendor": os.path.join(project_root, "_vendor"),
    "lib": os.path.join(project_root, "lib"),
    "bin": os.path.join(project_root, "bin"),
    "build_info": os.path.join(project_root, "build_env_info.txt"),
    "build_tools": os.path.join(project_root, "build_tools.json"),
    "build_inodes": os.path.join(project_root, "python_inodes.json"),
    "build_index": os.path.join(project_root, "build_fs.index")
}

# Link Vendor Libraries
if os.path.exists(paths["vendor"]):
    if paths["vendor"] not in sys.path:
        sys.path.insert(0, paths["vendor"])
    os.environ["PYTHONPATH"] = f"{paths['vendor']}:{os.environ.get('PYTHONPATH', '')}"

# Link Executables
if os.path.exists(paths["bin"]):
    os.environ["PATH"] = f"{paths['bin']}:{os.environ.get('PATH', '')}"
    subprocess.run(f"chmod -R +x {paths['bin']}", shell=True, stderr=subprocess.DEVNULL)

if os.path.exists(paths["lib"]):
    os.environ["LD_LIBRARY_PATH"] = f"{paths['lib']}:{os.environ.get('LD_LIBRARY_PATH', '')}"

# ========================================================
# 2. RUNTIME CHECKS & IMPORTS
# ========================================================
av_status = "Initializing..."
try:
    import av
    av_status = f"✅ PyAV {av.__version__} | Codecs: {len(av.codecs_available)}"
except Exception as e:
    av_status = f"❌ PyAV Error: {e}"

app = FastAPI()

# --- CORS MIDDLEWARE ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================================================
# 3. HELPER FUNCTIONS & CACHE
# ========================================================
BUILD_FS_CACHE: Dict[str, List[dict]] = {}

def get_human_size(size_bytes):
    if isinstance(size_bytes, str): return size_bytes
    for unit in ['B','KB','MB','GB']:
        if size_bytes < 1024: return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

def load_build_fs_cache():
    if not os.path.exists(paths["build_index"]): return
    try:
        dir_stack = [] 
        with open(paths["build_index"], 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.lstrip(' ')
                if not stripped: continue
                content = stripped.rstrip('\n')
                depth = len(line) - len(stripped)
                is_dir = content.endswith('/')
                name = content.rstrip('/')
                
                if depth == 0:
                    current_path = "/" if name == "" else name
                    dir_stack = [current_path]
                    if current_path not in BUILD_FS_CACHE:
                        BUILD_FS_CACHE[current_path] = []
                    continue

                while len(dir_stack) > depth: dir_stack.pop()
                parent_path = dir_stack[-1]
                if parent_path == "/": abs_path = f"/{name}"
                else: abs_path = f"{parent_path}/{name}"
                
                if parent_path not in BUILD_FS_CACHE: BUILD_FS_CACHE[parent_path] = []
                
                BUILD_FS_CACHE[parent_path].append({
                    "name": name, "path": abs_path, "is_dir": is_dir, "size": "-",
                    "ext": os.path.splitext(name)[1].lower() if not is_dir else ""
                })
                
                if is_dir:
                    dir_stack.append(abs_path)
                    if abs_path not in BUILD_FS_CACHE: BUILD_FS_CACHE[abs_path] = []
    except Exception as e: print(f"Error loading tree index: {e}")

load_build_fs_cache()

def get_size_str(path):
    total = 0
    try:
        if os.path.isfile(path): total = os.path.getsize(path)
        else:
            res = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE, text=True)
            total = int(res.stdout.split()[0])
    except: pass
    return get_human_size(total)

def get_runtime_env_info():
    info = { "python": sys.version.split()[0], "platform": platform.platform(), "glibc": platform.libc_ver()[1] }
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f: info["os"] = f.read().splitlines()[0].replace('"', '')
        else: info["os"] = "Unknown OS"
    except: info["os"] = "Error reading OS"
    return info

def compare_tools():
    build_data = {}
    if os.path.exists(paths["build_tools"]):
        try:
            with open(paths["build_tools"], 'r') as f: build_data = json.load(f)
        except: pass
    tool_list = list(build_data.keys()) if build_data else ['tree', 'jq', 'curl', 'git', 'python3']
    comparison = []
    for tool in tool_list:
        build_path = build_data.get(tool)
        runtime_path = shutil.which(tool)
        status = "Unknown"
        if build_path and runtime_path: status = "✅ Same Path" if build_path == runtime_path else "⚠️ Path Changed"
        elif build_path and not runtime_path: status = "❌ Missing in Runtime"
        elif not build_path and runtime_path: status = "✨ New in Runtime"
        else: status = "⛔ Not Available"
        comparison.append({ "name": tool, "build": build_path or "-", "runtime": runtime_path or "-", "status": status })
    return comparison

def get_python_inodes():
    if os.path.exists(paths["build_inodes"]):
        try:
            with open(paths["build_inodes"], 'r') as f: return json.load(f)
        except: pass
    return []

# ========================================================
# 4. API ENDPOINTS
# ========================================================
class FlyRequest(BaseModel):
    url: str
    cookies: str
    chunk_size: str = "8M"
    limit_rate: str = "4M"
    wait_time: str = "2"
    player_clients: str = "tv,android,ios"
    po_token: str = ""
    provider: str = "assemblyai"
    mode: str = "debug"
    deepgram_key: Optional[str] = ""
    assemblyai_key: Optional[str] = ""

@app.post("/api/fly")
async def fly_process(payload: FlyRequest):
    q = asyncio.Queue()
    
    asyncio.create_task(testfly.run_fly_process(
        log_queue=q,
        url=payload.url,
        cookies=payload.cookies,
        chunk_size=payload.chunk_size,
        limit_rate=payload.limit_rate,
        player_clients=payload.player_clients, 
        wait_time=payload.wait_time,
        po_token=payload.po_token,
        provider=payload.provider,
        mode=payload.mode,
        dg_key=payload.deepgram_key,
        aai_key=payload.assemblyai_key
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
        items = BUILD_FS_CACHE.get(lookup_path, [])
        return {"current_path": path, "items": items, "source": "build"}

    if not os.path.exists(path): raise HTTPException(404, "Path not found")
    items = []
    try:
        with os.scandir(path) as entries:
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    items.append({
                        "name": e.name, "path": e.path, "is_dir": e.is_dir(),
                        "size": get_size_str(e.path) if not e.is_dir() else "-",
                        "ext": os.path.splitext(e.name)[1].lower() if not e.is_dir() else ""
                    })
                except: continue
        return {"current_path": path, "items": items, "source": "runtime"}
    except Exception as e: raise HTTPException(403, str(e))

@app.get("/api/shell")
def run_shell(cmd: str):
    if not cmd: return {"out": ""}
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10, cwd=project_root, env=os.environ)
        return {"out": res.stdout}
    except subprocess.TimeoutExpired: return {"out": "⚠️ Command timed out."}
    except Exception as e: return {"out": str(e)}

@app.get("/api/stats")
def stats_endpoint():
    stats = []
    locations = [("App Code", paths["root"]), ("Dependencies", paths["vendor"]), ("Binaries", paths["bin"]), ("Temp", "/tmp")]
    for label, path in locations:
        if os.path.exists(path): stats.append({"label": label, "path": path, "size": get_size_str(path)})
    return {
        "storage": stats, "av": av_status, "runtime": get_runtime_env_info(),
        "tools": compare_tools(), "inodes": get_python_inodes(), "has_build_index": bool(BUILD_FS_CACHE)
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

# ========================================================
# 5. UI RESPONSE
# ========================================================
@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vercel Control</title>
    <style>
        :root {{ 
            --bg: #0d1117; 
            --surface: #161b22; 
            --border: #30363d; 
            --text: #c9d1d9; 
            --text-muted: #8b949e;
            --accent: #58a6ff; 
            --danger: #f85149; 
            --success: #3fb950;
            --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; 
        }}
        * {{ box-sizing: border-box; outline: none; }}
        body {{ margin: 0; background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; line-height: 1.5; }}
        
        /* Navbar */
        nav {{
            background: var(--surface);
            border-bottom: 1px solid var(--border);
            padding: 0 20px;
            height: 56px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 50;
        }}
        .brand {{ font-weight: 600; font-size: 16px; color: #fff; display: flex; align-items: center; gap: 8px; }}
        .nav-links {{ display: flex; gap: 4px; }}
        .nav-btn {{ 
            padding: 6px 12px; 
            border-radius: 6px; 
            cursor: pointer; 
            color: var(--text-muted); 
            font-size: 13px;
            font-weight: 500;
            transition: 0.2s;
        }}
        .nav-btn:hover {{ background: rgba(255,255,255,0.05); color: var(--text); }}
        .nav-btn.active {{ background: rgba(255,255,255,0.1); color: #fff; }}

        /* Container */
        main {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        
        .view {{ display: none; }}
        .view.active {{ display: block; }}

        /* Cards & Sections */
        .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; margin-bottom: 20px; }}
        .card-head {{ padding: 12px 16px; border-bottom: 1px solid var(--border); font-weight: 600; display: flex; justify-content: space-between; align-items: center; background: rgba(255,255,255,0.02); }}
        .card-body {{ padding: 16px; }}

        /* Explorer */
        .path-bar-container {{ display: flex; gap: 10px; margin-bottom: 15px; }}
        .path-input {{ flex: 1; background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 6px; font-family: var(--mono); font-size: 13px; }}
        .btn {{ background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; }}
        .btn:hover {{ border-color: var(--text-muted); }}
        .btn-primary {{ background: #238636; border-color: rgba(240,246,252,0.1); color: white; }}
        .btn-primary:hover {{ background: #2ea043; }}

        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; padding: 8px 12px; color: var(--text-muted); font-size: 12px; font-weight: 600; border-bottom: 1px solid var(--border); }}
        td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 13px; }}
        tr:last-child td {{ border-bottom: none; }}
        tr.item-row:hover {{ background: rgba(255,255,255,0.04); cursor: pointer; }}
        .icon {{ display: inline-block; width: 20px; text-align: center; margin-right: 8px; }}
        .tag {{ background: rgba(110,118,129,0.4); padding: 2px 6px; border-radius: 10px; font-size: 10px; font-weight: 600; }}
        .badge-snapshot {{ background: #d29922; color: #000; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700; margin-left: 10px; display: none; }}

        /* Terminal */
        .terminal-window {{ background: #000; border-radius: 6px; border: 1px solid var(--border); font-family: var(--mono); height: 500px; display: flex; flex-direction: column; }}
        .term-out {{ flex: 1; padding: 12px; overflow-y: auto; color: #c9d1d9; font-size: 12px; white-space: pre-wrap; }}
        .term-in-row {{ display: flex; border-top: 1px solid #333; }}
        .term-ps {{ padding: 10px; color: var(--success); }}
        .term-in {{ flex: 1; background: transparent; border: none; color: #fff; padding: 10px 0; font-family: inherit; }}

        /* TestFly Form */
        .grid-form {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; }}
        .form-group {{ margin-bottom: 5px; }}
        .form-group label {{ display: block; font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; }}
        .form-control {{ width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--text); padding: 8px; border-radius: 4px; font-family: var(--mono); font-size: 12px; }}
        .form-control:focus {{ border-color: var(--accent); }}
        textarea.form-control {{ resize: vertical; min-height: 80px; }}
        
        /* Stats */
        .stat-bar {{ height: 6px; background: rgba(255,255,255,0.1); border-radius: 3px; overflow: hidden; margin-top: 6px; }}
        .stat-fill {{ height: 100%; background: var(--accent); }}
        
        /* Modal */
        .modal {{ position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(2px); display: none; align-items: center; justify-content: center; z-index: 100; }}
        .modal-box {{ background: var(--surface); width: 80%; max-width: 900px; height: 80vh; border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; box-shadow: 0 20px 50px rgba(0,0,0,0.5); }}
        .modal-header {{ padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }}
        .modal-body {{ flex: 1; padding: 16px; overflow: auto; background: var(--bg); font-family: var(--mono); white-space: pre-wrap; font-size: 12px; }}

        /* Helpers */
        .text-success {{ color: var(--success); }}
        .text-danger {{ color: var(--danger); }}
        .text-muted {{ color: var(--text-muted); }}
    </style>
</head>
<body>

<nav>
    <div class="brand">⚡ Vercel Control</div>
    <div class="nav-links">
        <div class="nav-btn active" onclick="switchTab('explorer')">Explorer</div>
        <div class="nav-btn" onclick="switchTab('terminal')">Terminal</div>
        <div class="nav-btn" onclick="switchTab('testfly')">TestFly</div>
        <div class="nav-btn" onclick="switchTab('stats'); loadStats()">Monitor</div>
    </div>
</nav>

<main>
    <!-- EXPLORER -->
    <div id="explorer" class="view active">
        <div class="path-bar-container">
            <button class="btn" onclick="upDir()">⬆</button>
            <input class="path-input" id="addr" value="{project_root}" onchange="nav(this.value)">
            <button class="btn" onclick="refresh()">⟳ Refresh</button>
            <span id="mode-badge" class="badge-snapshot">SNAPSHOT</span>
        </div>

        <div class="card">
            <div class="card-head">
                <div style="display:flex; gap:10px;">
                    <span style="cursor:pointer" onclick="setMode('runtime'); nav('{project_root}')">📁 App Root</span>
                    <span style="color:var(--border)">|</span>
                    <span style="cursor:pointer" onclick="setMode('runtime'); nav('/')">💻 System</span>
                    <span style="color:var(--border)">|</span>
                    <span style="cursor:pointer" onclick="setMode('build'); nav('{project_root}')">🏗️ Build Snapshot</span>
                </div>
                <span class="text-muted" style="font-size:11px">Double click to open</span>
            </div>
            <table style="margin-bottom: 0;">
                <thead><tr><th>Name</th><th>Size</th><th>Type</th><th style="text-align:right">Actions</th></tr></thead>
                <tbody id="file-list"></tbody>
            </table>
        </div>
    </div>

    <!-- TERMINAL -->
    <div id="terminal" class="view">
        <div class="terminal-window">
            <div class="term-out" id="term-out">Welcome to Vercel Shell v1.0\nType 'help' or any linux command.</div>
            <div class="term-in-row">
                <span class="term-ps">$</span>
                <input id="term-in" class="term-in" autocomplete="off" autofocus>
            </div>
        </div>
    </div>

    <!-- TESTFLY -->
    <div id="testfly" class="view">
        <div class="card">
            <div class="card-head">Job Configuration</div>
            <div class="card-body">
                <div class="grid-form">
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label>Target URL</label>
                        <input id="fly-url" class="form-control" placeholder="https://youtube.com/watch?v=...">
                    </div>
                    
                    <div class="form-group">
                        <label>Provider</label>
                        <select id="fly-provider" class="form-control">
                            <option value="assemblyai">AssemblyAI</option>
                            <option value="deepgram">Deepgram</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Mode</label>
                        <select id="fly-mode" class="form-control">
                            <option value="debug">Debug (Verbose)</option>
                            <option value="data">Data (JSON only)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Chunk Size</label>
                        <input id="fly-chunk" class="form-control" value="8M">
                    </div>
                    <div class="form-group">
                        <label>Limit Rate</label>
                        <input id="fly-limit" class="form-control" value="4M">
                    </div>
                    
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label>API Key (Optional if Env Var set)</label>
                        <input id="fly-key" class="form-control" type="password" placeholder="Key override...">
                    </div>
                    
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label>Cookies (Netscape Format)</label>
                        <textarea id="fly-cookies" class="form-control" placeholder="# Netscape HTTP Cookie File..."></textarea>
                    </div>

                    <!-- Hidden Params defaults -->
                    <input id="fly-wait" value="2">
                    <input id="fly-clients" value="tv,android,ios">
                    <input id="fly-token" value="">
                </div>
                <div style="margin-top: 15px; text-align: right;">
                    <button class="btn btn-primary" onclick="runFly()">🚀 Launch Job</button>
                </div>
            </div>
        </div>
        
        <div class="terminal-window" style="height: 300px;">
            <div class="term-out" id="fly-out" style="color:#a5d6ff">Job logs will appear here...</div>
        </div>
    </div>

    <!-- MONITOR -->
    <div id="stats" class="view">
        <div class="grid-form">
            <!-- System Info -->
            <div class="card">
                <div class="card-head">System Runtime</div>
                <div class="card-body" id="sys-info" style="font-size:12px; color:var(--text-muted); line-height:1.8">Loading...</div>
            </div>

            <!-- Storage -->
            <div class="card">
                <div class="card-head">Storage Usage</div>
                <div class="card-body" id="storage-list">Loading...</div>
            </div>
        </div>

        <div class="card">
            <div class="card-head">Python Identity Check (Inodes)</div>
            <table class="table">
                <thead><tr><th>Path</th><th>Inode</th><th>Status</th></tr></thead>
                <tbody id="inode-list"></tbody>
            </table>
        </div>

        <div class="card">
            <div class="card-head">Toolchain Availability</div>
            <table>
                <thead><tr><th>Tool</th><th>Build Path</th><th>Runtime Path</th><th>Status</th></tr></thead>
                <tbody id="tool-comp-list"></tbody>
            </table>
        </div>
    </div>

</main>

<!-- Modal -->
<div class="modal" id="file-modal">
    <div class="modal-box">
        <div class="modal-header">
            <span id="modal-title" style="font-weight:600">File Content</span>
            <button class="btn" onclick="closeModal()">Close</button>
        </div>
        <div class="modal-body" id="modal-text"></div>
    </div>
</div>

<script>
    let currentPath = '{project_root}';
    let currentSource = 'runtime';

    // Tabs
    function switchTab(id) {{
        document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
        
        document.getElementById(id).classList.add('active');
        // Find button that triggers this
        const btn = Array.from(document.querySelectorAll('.nav-btn')).find(b => b.getAttribute('onclick').includes(id));
        if(btn) btn.classList.add('active');
    }}

    function setMode(mode) {{
        currentSource = mode;
        const badge = document.getElementById('mode-badge');
        const input = document.getElementById('addr');
        
        if (mode === 'build') {{
            badge.style.display = 'inline-block';
            input.style.borderColor = '#d29922';
        }} else {{
            badge.style.display = 'none';
            input.style.borderColor = 'var(--border)';
        }}
        refresh();
    }}

    async function nav(path) {{
        currentPath = path;
        document.getElementById('addr').value = path;
        const tbody = document.getElementById('file-list');
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding: 20px;">Loading...</td></tr>';

        try {{
            const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}&source=${{currentSource}}`);
            if(!res.ok) throw await res.text();
            const data = await res.json();
            
            tbody.innerHTML = '';
            if(!data.items || data.items.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding: 20px; color: var(--text-muted)">Directory is empty</td></tr>';
                return;
            }}

            data.items.forEach(item => {{
                const tr = document.createElement('tr');
                tr.className = 'item-row';
                const icon = item.is_dir ? '📁' : '📄';
                
                // Action Buttons
                let actions = '';
                if (!item.is_dir && currentSource === 'runtime') {{
                    actions += `<button class="btn" style="padding:2px 6px; margin-right:5px" onclick="event.stopPropagation(); window.open('/api/download?path=${{encodeURIComponent(item.path)}}')">⬇</button>`;
                    actions += `<button class="btn" style="padding:2px 6px; color:var(--danger)" onclick="del(event, '${{item.path}}')">✕</button>`;
                }} else if (!item.is_dir && currentSource === 'build') {{
                    actions = '<span class="text-muted" style="font-size:11px">Read Only</span>';
                }}

                tr.innerHTML = `
                    <td><span class="icon">${{icon}}</span> ${{item.name}}</td>
                    <td style="font-family:var(--mono); color:var(--text-muted)">${{item.size}}</td>
                    <td><span class="tag">${{item.ext || 'DIR'}}</span></td>
                    <td style="text-align:right">${{actions}}</td>
                `;
                tr.onclick = (e) => {{
                    if(e.target.tagName === 'BUTTON') return;
                    if (item.is_dir) nav(item.path);
                    else if (currentSource === 'runtime') viewFile(item.path);
                    else alert("Build snapshot files cannot be viewed directly via API.");
                }};
                tbody.appendChild(tr);
            }});
        }} catch(e) {{
            tbody.innerHTML = `<tr><td colspan="4" class="text-danger" style="text-align:center; padding: 20px;">Error: ${{e}}</td></tr>`;
        }}
    }}

    function upDir() {{
        const parts = currentPath.split('/').filter(p => p);
        parts.pop();
        nav(parts.length ? '/' + parts.join('/') : '/');
    }}
    
    function refresh() {{ nav(currentPath); }}

    // File Viewing
    async function viewFile(path) {{
        const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
        const data = await res.json();
        document.getElementById('modal-title').innerText = path.split('/').pop();
        document.getElementById('modal-text').innerText = data.content || data.error;
        document.getElementById('file-modal').style.display = 'flex';
    }}
    function closeModal() {{ document.getElementById('file-modal').style.display = 'none'; }}
    
    // Deletion
    async function del(e, path) {{
        e.stopPropagation();
        if(!confirm(`Delete ${{path}}?`)) return;
        await fetch(`/api/delete?path=${{encodeURIComponent(path)}}`);
        refresh();
    }}

    // Terminal
    const termIn = document.getElementById('term-in');
    const termOut = document.getElementById('term-out');
    termIn.addEventListener('keypress', async (e) => {{
        if(e.key === 'Enter') {{
            const cmd = termIn.value;
            termIn.value = '';
            termOut.innerText += `\\n$ ${{cmd}}`;
            if(cmd === 'clear') {{ termOut.innerText = ''; return; }}
            
            try {{
                const res = await fetch(`/api/shell?cmd=${{encodeURIComponent(cmd)}}`);
                const data = await res.json();
                termOut.innerText += `\\n${{data.out}}`;
            }} catch(e) {{
                termOut.innerText += `\\nError: ${{e}}`;
            }}
            termOut.scrollTop = termOut.scrollHeight;
        }}
    }});

    // Stats
    async function loadStats() {{
        const res = await fetch('/api/stats');
        const data = await res.json();
        
        // Runtime Info
        const info = data.runtime;
        document.getElementById('sys-info').innerHTML = `
            <b>OS:</b> ${{info.os}} (${{info.platform}})<br>
            <b>Python:</b> ${{info.python}} &nbsp;|&nbsp; <b>Glibc:</b> ${{info.glibc}}<br>
            <b>AV Support:</b> ${{data.av}}<br>
            <b>Build Index:</b> ${{data.has_build_index ? '<span class="text-success">✅ Loaded</span>' : '<span class="text-danger">❌ Missing</span>'}}
        `;

        // Inodes
        const iBody = document.getElementById('inode-list');
        iBody.innerHTML = '';
        data.inodes.forEach(i => {{
             iBody.innerHTML += `<tr><td style="font-family:var(--mono)">${{i.path}}</td><td style="font-family:var(--mono)">${{i.inode}}</td><td>${{i.status}}</td></tr>`;
        }});

        // Tools
        const tBody = document.getElementById('tool-comp-list');
        tBody.innerHTML = '';
        data.tools.forEach(t => {{
            const cls = t.status.includes('❌') ? 'text-danger' : t.status.includes('⛔') ? 'text-muted' : 'text-success';
            tBody.innerHTML += `<tr><td><b>${{t.name}}</b></td><td style="font-family:var(--mono);font-size:12px">${{t.build}}</td><td style="font-family:var(--mono);font-size:12px">${{t.runtime}}</td><td class="${{cls}}">${{t.status}}</td></tr>`;
        }});

        // Storage
        const sList = document.getElementById('storage-list');
        sList.innerHTML = '';
        data.storage.forEach(s => {{
            let rawSize = parseFloat(s.size); 
            if(s.size.includes('MB')) rawSize *= 1024*1024;
            if(s.size.includes('KB')) rawSize *= 1024;
            // Scale bar based on arbitrary 500MB max for visualization
            const pct = Math.min(100, (rawSize / (512*1024*1024)) * 100);
            
            sList.innerHTML += `
                <div style="margin-bottom:12px">
                    <div style="display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px">
                        <span>${{s.label}} <span class="text-muted" style="font-size:11px">(${{s.path}})</span></span>
                        <span style="font-family:var(--mono)">${{s.size}}</span>
                    </div>
                    <div class="stat-bar"><div class="stat-fill" style="width:${{pct}}%"></div></div>
                </div>
            `;
        }});
    }}

    // TestFly
    async function runFly() {{
        const out = document.getElementById('fly-out');
        const provider = document.getElementById('fly-provider').value;
        const key = document.getElementById('fly-key').value;
        
        const payload = {{
            url: document.getElementById('fly-url').value,
            cookies: document.getElementById('fly-cookies').value,
            chunk_size: document.getElementById('fly-chunk').value,
            limit_rate: document.getElementById('fly-limit').value,
            wait_time: document.getElementById('fly-wait').value,
            player_clients: document.getElementById('fly-clients').value,
            po_token: document.getElementById('fly-token').value,
            provider: provider,
            mode: document.getElementById('fly-mode').value,
            deepgram_key: (provider === 'deepgram') ? key : "",
            assemblyai_key: (provider === 'assemblyai') ? key : ""
        }};
        
        if(!payload.url) return alert("Target URL is required");

        out.innerText = "🚀 Job Started...\\n";
        
        try {{
            const res = await fetch('/api/fly', {{ 
                method: 'POST', 
                headers: {{'Content-Type': 'application/json'}}, 
                body: JSON.stringify(payload) 
            }});
            
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            
            while(true) {{
                const {{value, done}} = await reader.read();
                if(done) break;
                out.innerText += decoder.decode(value, {{stream: true}});
                out.scrollTop = out.scrollHeight;
            }}
            out.innerText += "\\n✅ Stream Closed.";
        }} catch(e) {{ 
            out.innerText += `\\n❌ Error: ${{e}}`; 
        }}
    }}

    // Init
    nav(currentPath);
</script>
</body>
</html>
    """
