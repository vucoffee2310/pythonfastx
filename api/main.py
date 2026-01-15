from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
import os
import sys
import subprocess
import mimetypes
import shutil
import platform
import asyncio
from datetime import datetime

# ========================================================
# 1. RUNTIME CONFIGURATION
# ========================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.exists("/var/task"):
    project_root = "/var/task"
else:
    project_root = os.getcwd()

vendor_path = os.path.join(project_root, "_vendor")
lib_path = os.path.join(project_root, "lib")
bin_path = os.path.join(project_root, "bin")
build_info_path = os.path.join(project_root, "build_env_info.txt")

# --- A. Link Python Modules (_vendor) ---
if os.path.exists(vendor_path):
    if vendor_path not in sys.path:
        sys.path.insert(0, vendor_path)
    current_pp = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = f"{vendor_path}:{current_pp}"

# --- B. Link Executables (PATH) ---
if os.path.exists(bin_path):
    os.environ["PATH"] = f"{bin_path}:{os.environ.get('PATH', '')}"
    try:
        subprocess.run(f"chmod -R +x {bin_path}", shell=True)
    except: pass

# --- C. Link Shared Libraries (LD_LIBRARY_PATH) ---
if os.path.exists(lib_path):
    os.environ["LD_LIBRARY_PATH"] = f"{lib_path}:{os.environ.get('LD_LIBRARY_PATH', '')}"

# ========================================================
# 2. ENV & PYAV STATUS CHECK
# ========================================================
def get_runtime_env_info():
    info = {
        "python_version": sys.version,
        "platform": platform.platform(),
        "glibc_python": platform.libc_ver()
    }
    try:
        res = subprocess.run(["ldd", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        info["ldd_raw"] = res.stdout
    except Exception as e:
        info["ldd_raw"] = f"Error: {e}"

    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release", "r") as f:
                info["os_release"] = f.read()
        else:
            info["os_release"] = "File /etc/os-release not found"
    except Exception as e:
        info["os_release"] = str(e)
        
    return info

print("--- RUNTIME ENVIRONMENT CHECK ---")
runtime_info = get_runtime_env_info()
print(f"OS: {runtime_info['platform']}")
print("---------------------------------")

av_msg = "Initializing..."
try:
    import av
    av_msg = f"✅ PyAV {av.__version__} Ready | Codecs: {len(av.codecs_available)}"
except ImportError as e:
    av_msg = f"❌ Import Error: {e} (Path: {sys.path})"
except Exception as e:
    av_msg = f"❌ Runtime Error: {e}"

# --- IMPORT TESTFLY ---
try:
    from . import testfly
except ImportError:
    import testfly

# ========================================================
# 3. HELPER FUNCTIONS
# ========================================================
def get_size_str(path):
    total = 0
    try:
        res = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE, text=True)
        total = int(res.stdout.split()[0])
    except:
        for dp, dn, fn in os.walk(path):
            for f in fn:
                try: total += os.path.getsize(os.path.join(dp, f))
                except: pass
    
    for unit in ['B','KB','MB','GB']:
        if total < 1024: return f"{total:.2f} {unit}"
        total /= 1024
    return f"{total:.2f} TB"

# ========================================================
# 4. API ROUTES
# ========================================================
app = FastAPI()

class FlyRequest(BaseModel):
    url: str
    cookies: str
    args: str = "youtube:player_client=all"

@app.post("/api/fly")
async def fly_process(payload: FlyRequest):
    """Starts the testfly process and streams logs."""
    q = asyncio.Queue()
    
    # Run in background with provided payload
    asyncio.create_task(testfly.run_fly_process(
        q, 
        payload.url, 
        payload.cookies, 
        payload.args
    ))
    
    async def log_generator():
        while True:
            data = await q.get()
            if data is None: break
            yield data
            
    return StreamingResponse(log_generator(), media_type="text/plain")

@app.get("/api/env")
def env_details():
    runtime = get_runtime_env_info()
    build_raw = "Build info file not found (maybe run locally?)."
    if os.path.exists(build_info_path):
        try:
            with open(build_info_path, "r") as f:
                build_raw = f.read()
        except Exception as e:
            build_raw = f"Error reading build info: {e}"
            
    return {"runtime": runtime, "build_raw": build_raw}

@app.get("/api/list")
def list_files(path: str = "/"):
    if not os.path.exists(path): raise HTTPException(404, "Path not found")
    items = []
    try:
        with os.scandir(path) as entries:
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    items.append({
                        "name": e.name, "path": e.path, "is_dir": e.is_dir(),
                        "size": get_size_str(e.path) if not e.is_dir() else "-",
                        "ext": os.path.splitext(e.name)[1].lower()
                    })
                except: continue
        return {"current_path": path, "items": items, "av_status": av_msg}
    except Exception as e: raise HTTPException(403, str(e))

@app.get("/api/shell")
def run_shell(cmd: str):
    if not cmd: return {"out": ""}
    try:
        res = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, timeout=5, cwd=project_root, env=os.environ
        )
        return {"out": res.stdout}
    except subprocess.TimeoutExpired: return {"out": "Error: Command timed out."}
    except Exception as e: return {"out": str(e)}

@app.get("/api/stats")
def system_stats():
    stats = []
    app_size_raw = 0
    locations = [
        ("App Code", "/var/task"),
        ("Vendor Libs", vendor_path),
        ("Binaries", bin_path),
        ("Libraries", lib_path),
        ("Temp", "/tmp")
    ]
    
    for label, path in locations:
        if os.path.exists(path):
            total = 0
            try:
                r = subprocess.run(["du","-sb",path], stdout=subprocess.PIPE, text=True)
                total = int(r.stdout.split()[0])
            except: pass
            if path == "/var/task": app_size_raw = total
            stats.append({"label": f"{label} ({path})", "size_fmt": get_size_str(path), "raw": total})

    return {"stats": stats, "warning": app_size_raw > 240*1024*1024}

@app.get("/api/view")
def view_file(path: str):
    if not os.path.exists(path): return {"error": "File not found"}
    try:
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary file cannot be viewed."}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except Exception as e: return {"error": str(e)}

@app.get("/api/delete")
def delete_file(path: str):
    try:
        if os.path.isdir(path): os.rmdir(path)
        else: os.remove(path)
        return {"ok": True}
    except OSError as e:
        return {"error": f"Failed: {e}"}

@app.get("/api/download")
def download(path: str):
    if os.path.exists(path): return FileResponse(path, filename=os.path.basename(path))

# ========================================================
# 5. FRONTEND (Single Page App)
# ========================================================
@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Vercel Control Panel</title>
    <style>
        :root {{ --bg:#fff; --side:#f8f9fa; --acc:#0070f3; --txt:#333; }}
        * {{ box-sizing:border-box; }}
        body {{ margin:0; font-family:-apple-system, sans-serif; height:100vh; display:flex; flex-direction:column; }}
        
        header {{ padding:10px; border-bottom:1px solid #ddd; background:#fff; display:flex; gap:10px; }}
        #addr {{ flex-grow:1; font-family:monospace; padding:6px; border:1px solid #ccc; border-radius:4px; }}
        button {{ padding:6px 12px; cursor:pointer; background:#fff; border:1px solid #ccc; border-radius:4px; }}
        button:hover {{ background:#eee; }}
        
        main {{ display:flex; flex-grow:1; overflow:hidden; }}
        aside {{ width:250px; background:var(--side); border-right:1px solid #ddd; padding:15px; display:flex; flex-direction:column; overflow-y:auto; }}
        
        .nav-head {{ font-size:11px; font-weight:bold; color:#888; margin-bottom:5px; margin-top:15px; text-transform:uppercase; }}
        .nav-item {{ padding:8px; cursor:pointer; font-size:13px; color:#555; border-radius:4px; margin-bottom:2px; }}
        .nav-item:hover {{ background:#eee; color:#000; }}
        .nav-item.active {{ background:white; color:var(--acc); font-weight:bold; border:1px solid #ddd; box-shadow:0 1px 2px rgba(0,0,0,0.05); }}
        
        #views {{ flex-grow:1; position:relative; background:var(--bg); }}
        .panel {{ position:absolute; inset:0; display:none; flex-direction:column; }}
        .panel.active {{ display:flex; }}
        
        /* Explorer */
        #list {{ flex-grow:1; overflow-y:auto; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th {{ text-align:left; background:#fafafa; padding:10px; border-bottom:1px solid #eee; position:sticky; top:0; }}
        td {{ padding:8px 10px; border-bottom:1px solid #f5f5f5; white-space:nowrap; }}
        tr.can-open {{ cursor:pointer; }}
        tr:hover {{ background:#f0f7ff; }}
        .act-btn {{ color:red; cursor:pointer; margin-left:10px; font-weight:bold; }}
        
        /* Terminal & Fly */
        #term-out, #fly-out {{ flex-grow:1; background:#1e1e1e; color:#ccc; padding:15px; font-family:monospace; white-space:pre-wrap; overflow-y:auto; }}
        #term-in {{ background:#333; color:white; border:none; padding:10px; font-family:monospace; outline:none; }}
        
        /* Stats */
        .stat-row {{ padding:15px; border-bottom:1px solid #eee; }}
        .bar-bg {{ height:6px; background:#eee; border-radius:3px; margin-top:5px; overflow:hidden; }}
        .bar-fill {{ height:100%; background:var(--acc); }}

        /* Env Info */
        pre.env-block {{ background:#f5f5f5; padding:10px; border-radius:5px; overflow-x:auto; font-size:12px; border:1px solid #ddd; }}
        h3 {{ margin-top:20px; margin-bottom:10px; border-bottom:1px solid #eee; padding-bottom:5px; }}
        
        /* Fly Form */
        .fly-form {{ padding:10px; border-bottom:1px solid #ddd; background:#f9f9f9; display:flex; flex-direction:column; gap:10px; }}
        .fly-row {{ display:flex; gap:10px; }}
        input, textarea {{ border:1px solid #ccc; padding:5px; border-radius:3px; font-family:monospace; font-size:12px; }}
        
        /* Modal */
        #modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:99; align-items:center; justify-content:center; }}
        .card {{ background:white; width:90%; height:90%; padding:20px; display:flex; flex-direction:column; border-radius:8px; }}
    </style>
</head>
<body>
<header>
    <button onclick="up()">⬆</button>
    <input id="addr" value="{project_root}">
    <button onclick="ref()">🔄</button>
</header>
<main>
    <aside>
        <div style="font-size:12px; padding:8px; background:white; border:1px solid #eee; border-radius:4px; margin-bottom:10px">
            {av_msg}
        </div>

        <div class="nav-head">Runtime Locations</div>
        <div class="nav-item" onclick="nav('{project_root}')">📁 App Code</div>
        <div class="nav-item" onclick="nav('{vendor_path}')">📦 _vendor</div>
        <div class="nav-item" onclick="nav('/')">💻 Root</div>
        <div class="nav-item" onclick="nav('/tmp')">♻️ Temp</div>
        
        <div class="nav-head">Tools</div>
        <div id="btn-exp" class="nav-item active" onclick="show('explorer')">📂 Explorer</div>
        <div id="btn-term" class="nav-item" onclick="show('terminal')">💻 Terminal</div>
        <div id="btn-fly" class="nav-item" onclick="show('fly')">🚀 TestFly Job</div>
        <div id="btn-stat" class="nav-item" onclick="loadStats()">📊 Storage Stats</div>
        <div id="btn-env" class="nav-item" onclick="loadEnv()">ℹ️ Environment</div>
        
        <div class="nav-head">Logs</div>
        <div class="nav-item" style="color:#0070f3" onclick="viewLog()">📜 Build Phase Snapshot</div>
    </aside>

    <div id="views">
        <!-- EXPLORER -->
        <div id="explorer" class="panel active">
            <div id="list">
                <table><thead><tr><th>Name</th><th>Size</th><th>Type</th><th>Actions</th></tr></thead><tbody id="tbody"></tbody></table>
            </div>
        </div>

        <!-- TERMINAL -->
        <div id="terminal" class="panel">
            <div id="term-out">Vercel Shell.\\nType 'tree', 'jq', 'ls -la', 'busybox'.\\n</div>
            <input id="term-in" placeholder="Command..." autocomplete="off">
        </div>
        
        <!-- TESTFLY -->
        <div id="fly" class="panel">
            <div class="fly-form">
                <div class="fly-row">
                    <input id="fly-url" style="flex:2" placeholder="YouTube URL (https://...)" value="https://www.youtube.com/watch?v=ZNdVzOBga6k">
                    <input id="fly-args" style="flex:3" placeholder="Extractor Args (po_token=...)" value='youtube:player_client=all;po_token=web.gvs+MlMQUj3TTz08aRBuqkQKUJI8sgaSz5WHWnAeQjJN7Jv-qhe-jZfl7VTihUv-RpMuTIpSK6hNhYf05Lt9IVFY-Gd4O1PI0miFlyOlU0zhdIr9Ac5aew=='>
                </div>
                <textarea id="fly-cookies" rows="4" placeholder="# Paste Netscape Cookies Content Here..."></textarea>
                <button style="background:var(--acc); color:white; border:none; padding:8px;" onclick="runFly()">▶ Start Processing Job</button>
            </div>
            <div id="fly-out">Ready. Paste cookies and click Start.</div>
        </div>
        
        <!-- STATS -->
        <div id="stats" class="panel" style="padding:20px; overflow-y:auto">
            <h2>Storage Usage</h2>
            <div id="stats-content">Loading...</div>
        </div>

        <!-- ENV INFO -->
        <div id="env" class="panel" style="padding:20px; overflow-y:auto">
            <h2>Environment Comparison</h2>
            <div id="env-content">Loading...</div>
        </div>
    </div>
</main>

<div id="modal">
    <div class="card">
        <div style="margin-bottom:10px"><button onclick="document.getElementById('modal').style.display='none'">Close</button></div>
        <pre id="m-text" style="flex-grow:1; overflow:auto; background:#f5f5f5; padding:10px"></pre>
    </div>
</div>

<script>
    let cur = '{project_root}';
    const txts = ['.py','.txt','.sh','.json','.md','.log','.env'];

    function show(id) {{
        document.querySelectorAll('.panel').forEach(e=>e.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        
        let btnId = 'btn-exp';
        if(id === 'terminal') btnId = 'btn-term';
        if(id === 'fly') btnId = 'btn-fly';
        if(id === 'stats') btnId = 'btn-stat';
        if(id === 'env') btnId = 'btn-env';
        document.getElementById(btnId).classList.add('active');
        
        if(id==='terminal') document.getElementById('term-in').focus();
    }}

    async function nav(p) {{
        show('explorer'); cur=p; document.getElementById('addr').value=p;
        const res = await fetch(`/api/list?path=${{encodeURIComponent(p)}}`);
        const d = await res.json();
        const b = document.getElementById('tbody'); b.innerHTML='';
        d.items.forEach(i => {{
            const tr = document.createElement('tr');
            if(i.is_dir || txts.includes(i.ext)) tr.className='can-open';
            tr.ondblclick = () => i.is_dir ? nav(i.path) : viewFile(i.path);
            tr.innerHTML = `<td>${{i.is_dir?'📁':'📄'}} ${{i.name}}</td><td>${{i.size}}</td><td>${{i.ext||'DIR'}}</td>
            <td>${{!i.is_dir?`<a href="/api/download?path=${{encodeURIComponent(i.path)}}" style="text-decoration:none">⬇</a>`:''}}
            <span class="act-btn" onclick="del(event,'${{i.path}}')">X</span></td>`;
            b.appendChild(tr);
        }});
    }}
    
    // --- TestFly Logic ---
    async function runFly() {{
        const out = document.getElementById('fly-out');
        const url = document.getElementById('fly-url').value;
        const cookies = document.getElementById('fly-cookies').value;
        const args = document.getElementById('fly-args').value;

        if(!url) return alert("URL required");
        
        out.textContent = "Writing cookies and starting job...\\n";
        
        try {{
            const response = await fetch('/api/fly', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{ url, cookies, args }})
            }});
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {{
                const {{ value, done }} = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, {{stream: true}});
                out.appendChild(document.createTextNode(chunk));
                out.scrollTop = out.scrollHeight;
            }}
            out.appendChild(document.createTextNode("\\n[Stream Connection Closed]"));
        }} catch(e) {{
            out.textContent += "\\nError: " + e;
        }}
    }}
    
    async function viewLog() {{ viewFile('/var/task/build_snapshot.log'); }}

    async function loadStats() {{
        show('stats');
        const c = document.getElementById('stats-content');
        c.innerHTML = 'Calculating sizes...';
        const res = await fetch('/api/stats');
        const d = await res.json();
        let h = '';
        if(d.warning) h += `<div style="padding:10px;background:#fee;color:red;border:1px solid red;margin-bottom:15px">⚠️ App size critical!</div>`;
        d.stats.forEach(s => {{
            let w = Math.min(100, (s.raw / 262144000)*100);
            h += `<div class="stat-row"><div style="display:flex;justify-content:space-between"><b>${{s.label}}</b><span>${{s.size_fmt}}</span></div>
            <div class="bar-bg"><div class="bar-fill" style="width:${{w}}%"></div></div></div>`;
        }});
        c.innerHTML = h;
    }}

    async function loadEnv() {{
        show('env');
        const c = document.getElementById('env-content');
        c.innerHTML = 'Fetching environment details...';
        const res = await fetch('/api/env');
        const d = await res.json();
        c.innerHTML = `
            <h3>🏃 Runtime Environment (Now)</h3>
            <pre class="env-block"><b>OS:</b> ${{d.runtime.platform}}\\n<b>GLIBC:</b> ${{d.runtime.glibc_python}}\\n<b>LDD:</b>\\n${{d.runtime.ldd_raw}}</pre>
            <h3>🏗️ Build Environment</h3>
            <pre class="env-block">${{d.build_raw}}</pre>
        `;
    }}

    async function viewFile(p) {{
        const res = await fetch(`/api/view?path=${{encodeURIComponent(p)}}`);
        const d = await res.json();
        document.getElementById('m-text').textContent = d.content || d.error;
        document.getElementById('modal').style.display='flex';
    }}

    async function del(e,p) {{
        e.stopPropagation();
        if(!confirm('Delete '+p+'?')) return;
        const res = await fetch(`/api/delete?path=${{encodeURIComponent(p)}}`);
        const d = await res.json();
        if(d.error) alert(d.error); else nav(cur);
    }}

    function up() {{ let p=cur.split('/').filter(x=>x); p.pop(); nav('/'+p.join('/')); }}
    function ref() {{ nav(cur); }}
    document.getElementById('addr').onkeypress = e => {{ if(e.key==='Enter') nav(e.target.value); }};

    const tin=document.getElementById('term-in'), tout=document.getElementById('term-out');
    tin.onkeypress = async e => {{
        if(e.key==='Enter') {{
            const c=tin.value; tin.value='';
            tout.appendChild(document.createTextNode('\\n$ '+c+'\\n'));
            if(c==='clear') {{ tout.innerHTML=''; return; }}
            const res = await fetch(`/api/shell?cmd=${{encodeURIComponent(c)}}`);
            const d = await res.json();
            tout.appendChild(document.createTextNode(d.out||''));
            tout.scrollTop=tout.scrollHeight;
        }}
    }};
    
    nav(cur);
</script>
</body>
</html>
    """
