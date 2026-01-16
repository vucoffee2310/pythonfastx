from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
import os
import sys
import subprocess
import asyncio
import platform
import shutil
import json
from typing import Optional, Dict, List

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

if os.path.exists(paths["vendor"]):
    if paths["vendor"] not in sys.path:
        sys.path.insert(0, paths["vendor"])
    os.environ["PYTHONPATH"] = f"{paths['vendor']}:{os.environ.get('PYTHONPATH', '')}"

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

try:
    from . import testfly
except ImportError:
    import testfly

app = FastAPI()

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
                    if current_path not in BUILD_FS_CACHE: BUILD_FS_CACHE[current_path] = []
                    continue
                while len(dir_stack) > depth: dir_stack.pop()
                parent_path = dir_stack[-1]
                abs_path = f"/{name}" if parent_path == "/" else f"{parent_path}/{name}"
                if parent_path not in BUILD_FS_CACHE: BUILD_FS_CACHE[parent_path] = []
                BUILD_FS_CACHE[parent_path].append({
                    "name": name, "path": abs_path, "is_dir": is_dir,
                    "size": "-", "ext": os.path.splitext(name)[1].lower() if not is_dir else ""
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
    info = {"python": sys.version.split()[0], "platform": platform.platform(), "glibc": platform.libc_ver()[1]}
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
        comparison.append({"name": tool, "build": build_path or "-", "runtime": runtime_path or "-", "status": status})
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
    provider: str = "assemblyai"
    chunk_size: str = "8M"
    limit_rate: str = "4M"
    wait_time: str = "2"
    player_clients: str = "tv,android,ios"
    po_token: str = ""

@app.post("/api/fly")
async def fly_process(payload: FlyRequest):
    q = asyncio.Queue()
    asyncio.create_task(testfly.run_fly_process(
        q, payload.url, payload.cookies, payload.chunk_size,
        payload.limit_rate, payload.player_clients, 
        payload.wait_time, payload.po_token, payload.provider
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
        lookup_path = path
        if len(lookup_path) > 1 and lookup_path.endswith('/'): lookup_path = lookup_path.rstrip('/')
        return {"current_path": path, "items": BUILD_FS_CACHE.get(lookup_path, []), "source": "build"}
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
    for label, path in [("App Code", paths["root"]), ("Dependencies", paths["vendor"]), ("Binaries", paths["bin"]), ("Temp", "/tmp")]:
        if os.path.exists(path): stats.append({"label": label, "path": path, "size": get_size_str(path)})
    return {"storage": stats, "av": av_status, "runtime": get_runtime_env_info(), "tools": compare_tools(), "inodes": get_python_inodes(), "has_build_index": bool(BUILD_FS_CACHE)}

@app.get("/api/view")
def view_file(path: str):
    if not os.path.exists(path): return {"error": "File not found"}
    try:
        if os.path.getsize(path) > 500_000: return {"error": "File too large."}
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary file."}
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
# 5. UI
# ========================================================
@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Server Control</title>
    <style>
        :root {{ --bg: #000; --surface: #111; --surface-hover: #1a1a1a; --border: #333; --text: #eaeaea; --accent: #0070f3; --danger: #e00; --font: -apple-system, sans-serif; --mono: monospace; }}
        * {{ box-sizing: border-box; outline: none; }}
        body {{ margin: 0; background: var(--bg); color: var(--text); font-family: var(--font); display: flex; height: 100vh; overflow: hidden; font-size: 13px; }}
        aside {{ width: 240px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; padding: 12px; }}
        main {{ flex: 1; display: flex; flex-direction: column; min-width: 0; }}
        .brand {{ font-weight: 700; margin-bottom: 20px; padding: 0 8px; font-size: 14px; }}
        .nav-group {{ margin-bottom: 20px; }}
        .nav-label {{ color: #888; font-size: 11px; font-weight: 600; text-transform: uppercase; padding: 0 8px 6px; }}
        .nav-item {{ padding: 8px; border-radius: 6px; cursor: pointer; color: #888; display: flex; align-items: center; gap: 8px; }}
        .nav-item:hover {{ background: var(--surface-hover); color: var(--text); }}
        .nav-item.active {{ background: var(--surface-hover); color: var(--text); font-weight: 500; }}
        header {{ height: 50px; border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 16px; gap: 12px; background: rgba(0,0,0,0.5); backdrop-filter: blur(5px); }}
        .path-bar {{ flex: 1; background: var(--surface); border: 1px solid var(--border); padding: 6px 10px; border-radius: 6px; color: var(--text); font-family: var(--mono); font-size: 12px; }}
        .icon-btn {{ background: transparent; border: 1px solid var(--border); color: var(--text); width: 28px; height: 28px; border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; }}
        #content {{ flex: 1; overflow: auto; }}
        .view {{ display: none; padding: 20px; height: 100%; }}
        .view.active {{ display: flex; flex-direction: column; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th {{ text-align: left; color: #888; padding: 8px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--bg); }}
        td {{ padding: 8px; border-bottom: 1px solid var(--border); }}
        .console {{ background: #000; border: 1px solid var(--border); border-radius: 8px; flex: 1; display: flex; flex-direction: column; font-family: var(--mono); overflow: hidden; }}
        .output {{ flex: 1; padding: 12px; overflow-y: auto; white-space: pre-wrap; font-size: 12px; color: #ccc; }}
        .input-line {{ display: flex; border-top: 1px solid var(--border); }}
        .input-line input {{ flex: 1; background: transparent; border: none; color: white; padding: 10px; font-family: inherit; }}
        .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
        .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }}
        .full-width {{ grid-column: 1 / -1; }}
        label {{ display: block; color: #888; font-size: 11px; margin-bottom: 6px; font-weight: 600; }}
        input, textarea, select {{ width: 100%; background: var(--bg); border: 1px solid var(--border); color: white; padding: 8px; border-radius: 4px; font-family: var(--mono); font-size: 12px; }}
        .btn-primary {{ background: var(--accent); color: white; border:none; width: 100%; padding: 10px; margin-top: 10px; cursor:pointer; font-weight:bold; border-radius:4px; }}
        .modal {{ position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: none; align-items: center; justify-content: center; z-index: 100; }}
        .modal-content {{ background: var(--surface); width: 80%; height: 80%; border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; }}
        .tag {{ background: var(--border); padding: 2px 6px; border-radius: 4px; font-size: 10px; color: #888; }}
        .badge-build {{ background: #f5a623; color: black; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px; margin-left: 5px; }}
    </style>
</head>
<body>
<aside>
    <div class="brand">⚡ Vercel Control</div>
    <div class="nav-group">
        <div class="nav-label">File System</div>
        <div class="nav-item active" onclick="setMode('runtime'); nav('{project_root}')">📁 App Root</div>
        <div class="nav-item" onclick="setMode('runtime'); nav('/')">💻 System Root</div>
        <div class="nav-item" onclick="setMode('build'); nav('{project_root}')">🏗️ Build Snapshot</div>
    </div>
    <div class="nav-group">
        <div class="nav-label">Tools</div>
        <div class="nav-item" onclick="setView('terminal')">💻 Terminal</div>
        <div class="nav-item" onclick="setView('fly')">🚀 TestFly Job</div>
    </div>
    <div class="nav-group">
        <div class="nav-label">Monitor</div>
        <div class="nav-item" onclick="setView('stats'); loadStats()">📊 Statistics</div>
    </div>
</aside>
<main>
    <header>
        <button class="icon-btn" onclick="upDir()">⬆</button>
        <input class="path-bar" id="addr" value="{project_root}" onchange="nav(this.value)">
        <span id="mode-badge" style="display:none" class="badge-build">SNAPSHOT</span>
        <button class="icon-btn" onclick="refresh()">⟳</button>
    </header>
    <div id="content">
        <div id="explorer" class="view active" style="padding:0">
            <table>
                <thead><tr><th style="padding-left:16px">Name</th><th>Size</th><th>Type</th><th>Action</th></tr></thead>
                <tbody id="file-list"></tbody>
            </table>
        </div>
        <div id="terminal" class="view">
            <div class="console">
                <div class="output" id="term-out">Welcome to Vercel Shell.</div>
                <div class="input-line"><span style="padding:10px;color:var(--accent)">$</span><input id="term-in" autocomplete="off"></div>
            </div>
        </div>
        <div id="fly" class="view">
            <div class="card">
                <div class="form-grid">
                    <div class="full-width"><label>YouTube URL</label><input id="fly-url" placeholder="https://youtube.com/watch?v=..."></div>
                    <div class="full-width">
                        <label>Logistics Provider</label>
                        <select id="fly-provider">
                            <option value="assemblyai">AssemblyAI (Upload Only)</option>
                            <option value="deepgram">Deepgram (Upload Only)</option>
                        </select>
                    </div>
                    <div><label>Chunk Size</label><input id="fly-chunk" value="8M"></div>
                    <div><label>Limit Rate</label><input id="fly-limit" value="4M"></div>
                    <div><label>Player Clients</label><input id="fly-clients" value="tv,android,ios"></div>
                    <div><label>Wait Time (s)</label><input id="fly-wait" value="2"></div>
                    <div class="full-width"><label>PO Token</label><input id="fly-token"></div>
                    <div class="full-width"><label>Cookies</label><textarea id="fly-cookies" rows="3"></textarea></div>
                    <div class="full-width"><button class="btn-primary" onclick="runFly()">Start Job</button></div>
                </div>
            </div>
            <div class="console" style="height: 300px"><div class="output" id="fly-out">Logs...</div></div>
        </div>
        <div id="stats" class="view">
            <div class="card"><h3>System Runtime</h3><div id="sys-info"></div></div>
            <div class="card"><h3>Storage</h3><div id="storage-list"></div></div>
        </div>
    </div>
</main>
<div class="modal" id="file-modal">
    <div class="modal-content">
        <div style="padding:10px; border-bottom:1px solid var(--border); display:flex; justify-content:space-between">
            <span id="modal-title"></span><button onclick="closeModal()">Close</button>
        </div>
        <div class="modal-body" id="modal-text" style="padding:10px; overflow:auto; font-family:var(--mono); white-space:pre-wrap"></div>
    </div>
</div>
<script>
    let currentPath = '{project_root}';
    let currentSource = 'runtime';
    function setView(id) {{ document.querySelectorAll('.view').forEach(el => el.classList.remove('active')); document.getElementById(id).classList.add('active'); }}
    function setMode(mode) {{ currentSource = mode; setView('explorer'); document.getElementById('mode-badge').style.display = (mode === 'build') ? 'inline-block' : 'none'; refresh(); }}
    async function nav(path) {{
        currentPath = path; document.getElementById('addr').value = path;
        const tbody = document.getElementById('file-list');
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:20px">Loading...</td></tr>';
        const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}&source=${{currentSource}}`);
        const data = await res.json();
        tbody.innerHTML = '';
        data.items.forEach(item => {{
            const tr = document.createElement('tr');
            tr.innerHTML = `<td style="padding-left:16px">${{item.is_dir?'📁':'📄'}} ${{item.name}}</td><td>${{item.size}}</td><td><span class="tag">${{item.ext||'DIR'}}</span></td><td></td>`;
            tr.onclick = () => item.is_dir ? nav(item.path) : viewFile(item.path);
            tbody.appendChild(tr);
        }});
    }}
    function upDir() {{ const p = currentPath.split('/').filter(x=>x); p.pop(); nav('/'+p.join('/')); }}
    function refresh() {{ nav(currentPath); }}
    async function viewFile(path) {{
        if(currentSource==='build') return alert("Cannot view build files");
        const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
        const data = await res.json();
        document.getElementById('modal-title').innerText = path;
        document.getElementById('modal-text').innerText = data.content || data.error;
        document.getElementById('file-modal').style.display = 'flex';
    }}
    function closeModal() {{ document.getElementById('file-modal').style.display = 'none'; }}
    async function runFly() {{
        const out = document.getElementById('fly-out');
        const payload = {{
            url: document.getElementById('fly-url').value,
            provider: document.getElementById('fly-provider').value,
            cookies: document.getElementById('fly-cookies').value,
            chunk_size: document.getElementById('fly-chunk').value,
            limit_rate: document.getElementById('fly-limit').value,
            wait_time: document.getElementById('fly-wait').value,
            player_clients: document.getElementById('fly-clients').value,
            po_token: document.getElementById('fly-token').value
        }};
        out.innerText = "🚀 Starting " + payload.provider + " job...\\n";
        const res = await fetch('/api/fly', {{ method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(payload) }});
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        while(true) {{
            const {{value, done}} = await reader.read();
            if(done) break;
            out.innerText += decoder.decode(value);
            out.scrollTop = out.scrollHeight;
        }}
    }}
    async function loadStats() {{
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('sys-info').innerText = JSON.stringify(data.runtime, null, 2);
    }}
    nav(currentPath);
</script>
</body>
</html>
    """
