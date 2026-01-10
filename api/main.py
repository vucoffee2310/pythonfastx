from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import sys
import ctypes
import subprocess
import mimetypes
import shutil
import pkg_resources
from datetime import datetime

# ========================================================
# 1. RUNTIME CONFIGURATION (Linker & Path Setup)
# ========================================================
# This section ensures Linux knows where to find your custom
# binaries (bin/) and shared libraries (lib/).

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
lib_path = os.path.join(project_root, "lib")
bin_path = os.path.join(project_root, "bin")

# --- A. Link Executables (PATH) ---
if os.path.exists(bin_path):
    # Prepend bin_path to PATH so 'tree' works directly
    os.environ["PATH"] = f"{bin_path}:{os.environ.get('PATH', '')}"
    try:
        # Ensure execution bits are set
        subprocess.run(f"chmod -R +x {bin_path}", shell=True)
    except: pass

# --- B. Link Libraries (LD_LIBRARY_PATH & Preload) ---
if os.path.exists(lib_path):
    # 1. Add to Python Path
    sys.path.append(lib_path)
    # 2. Add to Linker Path
    os.environ["LD_LIBRARY_PATH"] = f"{lib_path}:{os.environ.get('LD_LIBRARY_PATH', '')}"

    # 3. Manually Pre-load Dependencies in Order
    # This prevents "Shared object not found" for libmp3lame/libogg
    load_order = [
        "libogg.so.0", "libvorbis.so.0", "libvorbisenc.so.2", "libvorbisfile.so.3",
        "libmp3lame.so.0", "libopus.so.0", "libspeex.so.1",
        "libavutil.so.60", "libswresample.so.6", "libswscale.so.9",
        "libavcodec.so.62", "libavformat.so.62", "libavdevice.so.62", "libavfilter.so.11"
    ]
    
    # Use RTLD_GLOBAL to make symbols available to PyAV
    flags = ctypes.RTLD_GLOBAL
    for lib in load_order:
        try:
            # Find the actual filename (ignoring version suffixes like .1.2)
            candidates = [f for f in os.listdir(lib_path) if f.startswith(lib)]
            if candidates:
                ctypes.CDLL(os.path.join(lib_path, candidates[0]), mode=flags)
        except: pass

# ========================================================
# 2. PYAV STATUS CHECK
# ========================================================
av_msg = "Initializing..."
try:
    import av
    av_msg = f"✅ PyAV {av.__version__} Ready | Codecs: {len(av.codecs_available)}"
except ImportError as e:
    av_msg = f"❌ Import Error: {e}"
except Exception as e:
    av_msg = f"❌ Runtime Error: {e}"

# ========================================================
# 3. HELPER FUNCTIONS
# ========================================================
def get_size_str(path):
    """Calculates folder size nicely."""
    total = 0
    # Use 'du' if available for speed
    try:
        res = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE, text=True)
        total = int(res.stdout.split()[0])
    except:
        # Fallback to python
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

@app.get("/api/list")
def list_files(path: str = "/"):
    if not os.path.exists(path): raise HTTPException(404, "Path not found")
    items = []
    try:
        with os.scandir(path) as entries:
            # Sort: Directories first, then files
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    s = e.stat()
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
    """Run a shell command (Stateless)."""
    if not cmd: return {"out": ""}
    try:
        # Run command with 5s timeout
        res = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, timeout=5, cwd=os.getcwd()
        )
        return {"out": res.stdout}
    except subprocess.TimeoutExpired: return {"out": "Error: Command timed out."}
    except Exception as e: return {"out": str(e)}

@app.get("/api/stats")
def system_stats():
    """Storage usage dashboard."""
    stats = []
    app_size_raw = 0
    
    # Check key directories
    locations = [
        ("App Code", "/var/task"),
        ("Libraries", lib_path),
        ("Tools", bin_path),
        ("Temp", "/tmp"),
        ("Python", "/var/lang")
    ]
    
    for label, path in locations:
        if os.path.exists(path):
            # Recalculate size
            total = 0
            try:
                r = subprocess.run(["du","-sb",path], stdout=subprocess.PIPE, text=True)
                total = int(r.stdout.split()[0])
            except: pass
            
            if path == "/var/task": app_size_raw = total
            
            stats.append({
                "label": f"{label} ({path})",
                "size_fmt": get_size_str(path),
                "raw": total
            })

    return {
        "stats": stats, 
        "warning": app_size_raw > 240*1024*1024 # Warn if close to 250MB limit
    }

@app.get("/api/view")
def view_file(path: str):
    try:
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary file"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(100_000)}
    except Exception as e: return {"error": str(e)}

@app.get("/api/delete")
def delete_file(path: str):
    try:
        if os.path.isdir(path): os.rmdir(path)
        else: os.remove(path)
        return {"ok": True}
    except OSError as e:
        msg = "Read-Only Filesystem" if e.errno == 30 else e.strerror
        return {"error": f"Failed: {msg}"}

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
        aside {{ width:250px; background:var(--side); border-right:1px solid #ddd; padding:15px; display:flex; flex-direction:column; }}
        
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
        
        /* Terminal */
        #term-out {{ flex-grow:1; background:#1e1e1e; color:#ccc; padding:15px; font-family:monospace; white-space:pre-wrap; overflow-y:auto; }}
        #term-in {{ background:#333; color:white; border:none; padding:10px; font-family:monospace; outline:none; }}
        
        /* Stats */
        .stat-row {{ padding:15px; border-bottom:1px solid #eee; }}
        .bar-bg {{ height:6px; background:#eee; border-radius:3px; margin-top:5px; overflow:hidden; }}
        .bar-fill {{ height:100%; background:var(--acc); }}
        
        /* Modal */
        #modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:99; align-items:center; justify-content:center; }}
        .card {{ background:white; width:90%; height:90%; padding:20px; display:flex; flex-direction:column; border-radius:8px; }}
    </style>
</head>
<body>
<header>
    <button onclick="up()">⬆</button>
    <input id="addr" value="/var/task">
    <button onclick="ref()">🔄</button>
</header>
<main>
    <aside>
        <div style="font-size:12px; padding:8px; background:white; border:1px solid #eee; border-radius:4px; margin-bottom:10px">
            {av_msg}
        </div>

        <div class="nav-head">Locations</div>
        <div class="nav-item" onclick="nav('/var/task')">📁 App Code</div>
        <div class="nav-item" onclick="nav('/')">💻 Root</div>
        <div class="nav-item" onclick="nav('/tmp')">♻️ Temp</div>
        <div class="nav-item" onclick="nav('{lib_path}')">📚 Libraries</div>
        
        <div class="nav-head">Tools</div>
        <div id="btn-exp" class="nav-item active" onclick="show('explorer')">📂 Explorer</div>
        <div id="btn-term" class="nav-item" onclick="show('terminal')">💻 Terminal</div>
        <div id="btn-stat" class="nav-item" onclick="loadStats()">📊 Storage Stats</div>
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
            <div id="term-out">Vercel Shell (Stateless).\\nType 'tree', 'jq', 'ls -la', 'busybox'.\\n</div>
            <input id="term-in" placeholder="Command..." autocomplete="off">
        </div>
        
        <!-- STATS -->
        <div id="stats" class="panel" style="padding:20px; overflow-y:auto">
            <h2>Storage Usage</h2>
            <div id="stats-content">Loading...</div>
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
    let cur = '/var/task';
    const txts = ['.py','.txt','.sh','.json','.md','.log','.env'];

    function show(id) {{
        document.querySelectorAll('.panel').forEach(e=>e.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.getElementById('btn-'+(id==='stats'?'stat':id==='explorer'?'exp':'term')).classList.add('active');
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

    async function loadStats() {{
        show('stats');
        const c = document.getElementById('stats-content');
        c.innerHTML = 'Calculating sizes...';
        const res = await fetch('/api/stats');
        const d = await res.json();
        let h = '';
        if(d.warning) h += `<div style="padding:10px;background:#fee;color:red;border:1px solid red;margin-bottom:15px">⚠️ App size critical!</div>`;
        d.stats.forEach(s => {{
            let w = Math.min(100, (s.raw / 262144000)*100); // % of 250MB
            h += `<div class="stat-row"><div style="display:flex;justify-content:space-between"><b>${{s.label}}</b><span>${{s.size_fmt}}</span></div>
            <div class="bar-bg"><div class="bar-fill" style="width:${{w}}%"></div></div></div>`;
        }});
        c.innerHTML = h;
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

    // Terminal
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
    
    // Init
    nav('/var/task');
</script>
</body>
</html>
    """
