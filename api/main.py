from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import sys
import ctypes
import subprocess
import datetime

# ==========================================
# 1. RUNTIME CONFIGURATION
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
lib_path = os.path.join(project_root, "lib")
bin_path = os.path.join(project_root, "bin")

# Link Tools
if os.path.exists(bin_path):
    os.environ["PATH"] = f"{bin_path}:{os.environ.get('PATH', '')}"
    try: subprocess.run(f"chmod -R +x {bin_path}", shell=True)
    except: pass

# Link Libraries
if os.path.exists(lib_path):
    sys.path.append(lib_path)
    os.environ["LD_LIBRARY_PATH"] = f"{lib_path}:{os.environ.get('LD_LIBRARY_PATH', '')}"
    
    # Preload dependencies for PyAV
    preload = ["libogg.so.0", "libvorbis.so.0", "libvorbisenc.so.2", "libvorbisfile.so.3", 
               "libmp3lame.so.0", "libopus.so.0", "libspeex.so.1", "libavutil.so.60", 
               "libswresample.so.6", "libswscale.so.9", "libavcodec.so.62", 
               "libavformat.so.62", "libavdevice.so.62", "libavfilter.so.11"]
    for name in preload:
        try:
            # Find actual file (ignoring minor version diffs)
            found = [f for f in os.listdir(lib_path) if f.startswith(name)]
            if found: ctypes.CDLL(os.path.join(lib_path, found[0]), mode=ctypes.RTLD_GLOBAL)
        except: pass

# ==========================================
# 2. STATUS CHECKS
# ==========================================
av_msg = "Init..."
try:
    import av
    av_msg = f"✅ PyAV {av.__version__} | Codecs: {len(av.codecs_available)}"
except Exception as e:
    av_msg = f"❌ {e}"

# ==========================================
# 3. UTILITIES
# ==========================================
def get_size(start_path):
    """Calculates total folder size in bytes."""
    if not os.path.exists(start_path): return 0
    total_size = 0
    # Try using 'du' command for speed (native linux)
    try:
        res = subprocess.run(["du", "-sb", start_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            return int(res.stdout.split()[0])
    except: pass
    
    # Fallback to python walk
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
    return total_size

def fmt_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024: return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

# ==========================================
# 4. API
# ==========================================
app = FastAPI()

@app.get("/api/list")
def list_dir(path: str = "/"):
    if not os.path.exists(path): raise HTTPException(404)
    items = []
    try:
        with os.scandir(path) as entries:
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                try:
                    s = e.stat()
                    items.append({
                        "name": e.name, "path": e.path, "is_dir": e.is_dir(),
                        "size": fmt_size(s.st_size) if not e.is_dir() else "-",
                        "ext": os.path.splitext(e.name)[1].lower()
                    })
                except: continue
        return {"path": path, "items": items}
    except Exception as e: raise HTTPException(403, str(e))

@app.get("/api/stats")
def get_stats():
    """Returns storage usage statistics."""
    # Define interesting paths
    targets = {
        "App Code (/var/task)": "/var/task",
        "Temp (/tmp)": "/tmp",
        "Python Runtime (/var/lang)": "/var/lang",
        "Custom Libs (/var/task/lib)": lib_path,
        "Custom Tools (/var/task/bin)": bin_path
    }
    
    data = []
    total_app_size = 0
    
    for label, path in targets.items():
        b = get_size(path)
        if path == "/var/task": total_app_size = b
        data.append({"label": label, "bytes": b, "fmt": fmt_size(b)})
        
    return {
        "storage": data,
        "av_status": av_msg,
        "limit_warning": total_app_size > (230 * 1024 * 1024) # Warn if > 230MB
    }

@app.get("/api/shell")
def shell(cmd: str):
    try:
        res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5, cwd=os.getcwd())
        return {"out": res.stdout}
    except Exception as e: return {"out": str(e)}

@app.get("/api/view")
def view(path: str):
    try:
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"err": "Binary file"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(100000)}
    except Exception as e: return {"err": str(e)}

@app.get("/api/download")
def dl(path: str):
    if os.path.exists(path): return FileResponse(path, filename=os.path.basename(path))

@app.get("/api/delete")
def rm(path: str):
    try:
        if os.path.isdir(path): os.rmdir(path)
        else: os.remove(path)
        return {"ok": True}
    except OSError as e: return {"err": f"Error {e.errno}: {e.strerror}"}

@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Vercel Manager</title>
    <style>
        :root {{ --bg:#fff; --sb:#f9f9f9; --acc:#0070f3; --txt:#333; }}
        body {{ margin:0; font-family:sans-serif; height:100vh; display:flex; flex-direction:column; color:var(--txt); }}
        header {{ padding:10px; background:#eee; border-bottom:1px solid #ddd; display:flex; gap:10px; }}
        #addr {{ flex-grow:1; padding:5px; border:1px solid #ccc; font-family:monospace; }}
        main {{ display:flex; flex-grow:1; overflow:hidden; }}
        aside {{ width:240px; background:var(--sb); border-right:1px solid #ddd; padding:15px; }}
        .btn {{ display:block; padding:8px; cursor:pointer; color:#555; border-radius:4px; margin-bottom:2px; font-size:13px; }}
        .btn:hover {{ background:#e0e0e0; color:black; }}
        .btn.active {{ background:white; color:var(--acc); font-weight:bold; border:1px solid #ddd; }}
        
        .panel {{ display:none; flex-grow:1; flex-direction:column; overflow:hidden; }}
        .panel.active {{ display:flex; }}
        
        /* Tables */
        #list {{ flex-grow:1; overflow-y:auto; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th {{ text-align:left; background:#fafafa; padding:10px; border-bottom:1px solid #ddd; position:sticky; top:0; }}
        td {{ padding:8px; border-bottom:1px solid #f5f5f5; white-space:nowrap; }}
        tr.can-open {{ cursor:pointer; }}
        tr:hover {{ background:#f0f7ff; }}
        
        /* Stats */
        .stat-card {{ padding:15px; border-bottom:1px solid #eee; }}
        .progress {{ height:8px; background:#eee; border-radius:4px; overflow:hidden; margin-top:5px; }}
        .bar {{ height:100%; background:var(--acc); }}
        
        /* Terminal */
        #term-out {{ flex-grow:1; background:#1e1e1e; color:#ccc; padding:15px; font-family:monospace; overflow-y:auto; white-space:pre-wrap; }}
        #term-in {{ background:#333; color:white; border:none; padding:10px; font-family:monospace; outline:none; }}
        
        /* Modal */
        #modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:9; align-items:center; justify-content:center; }}
        .card {{ background:white; width:90%; height:90%; padding:20px; display:flex; flex-direction:column; border-radius:8px; }}
    </style>
</head>
<body>
<header>
    <button onclick="up()">⬆</button>
    <input id="addr">
    <button onclick="ref()">🔄</button>
</header>
<main>
    <aside>
        <div style="font-size:11px; font-weight:bold; color:#999; margin-bottom:10px">LOCATIONS</div>
        <div class="btn" onclick="nav('/var/task')">📁 App Code</div>
        <div class="btn" onclick="nav('/')">💻 Root</div>
        <div class="btn" onclick="nav('/tmp')">♻️ Temp</div>
        <div class="btn" onclick="nav('{lib_path}')">📚 Libs</div>
        
        <div style="font-size:11px; font-weight:bold; color:#999; margin:20px 0 10px">VIEWS</div>
        <div id="b-exp" class="btn active" onclick="view('explorer')">📂 Explorer</div>
        <div id="b-term" class="btn" onclick="view('terminal')">💻 Terminal</div>
        <div id="b-stat" class="btn" onclick="loadStats()">📊 Storage & Stats</div>
    </aside>

    <!-- EXPLORER -->
    <div id="explorer" class="panel active">
        <div id="list"><table><thead><tr><th>Name</th><th>Size</th><th>Type</th><th>Act</th></tr></thead><tbody id="tbody"></tbody></table></div>
    </div>

    <!-- TERMINAL -->
    <div id="terminal" class="panel">
        <div id="term-out">Vercel Web Shell.</div>
        <input id="term-in" placeholder="ls -la, tree, busybox df -h" autocomplete="off">
    </div>

    <!-- STATS -->
    <div id="stats" class="panel" style="padding:20px; overflow-y:auto">
        <h2 style="margin-top:0">System Storage</h2>
        <div id="stats-body">Loading...</div>
    </div>
</main>

<div id="modal">
    <div class="card">
        <div style="margin-bottom:10px"><button onclick="document.getElementById('modal').style.display='none'">Close</button></div>
        <pre id="m-text" style="flex-grow:1; overflow:auto; background:#f4f4f4; padding:10px"></pre>
    </div>
</div>

<script>
    let cur='/var/task';
    const txts=['.py','.txt','.sh','.json','.log','.md','.env'];
    
    function view(id){{
        document.querySelectorAll('.panel').forEach(e=>e.classList.remove('active'));
        document.querySelectorAll('.btn').forEach(e=>e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.getElementById('b-'+(id==='explorer'?'exp':id==='terminal'?'term':'stat')).classList.add('active');
        if(id==='terminal') document.getElementById('term-in').focus();
    }}
    
    async function nav(p){{
        view('explorer'); cur=p; document.getElementById('addr').value=p;
        const res=await fetch(`/api/list?path=${{encodeURIComponent(p)}}`);
        const d=await res.json();
        const b=document.getElementById('tbody'); b.innerHTML='';
        d.items.forEach(i=>{{
            const tr=document.createElement('tr');
            const open=i.is_dir||txts.includes(i.ext);
            if(open) tr.className='can-open';
            tr.ondblclick=()=>i.is_dir?nav(i.path):show(i.path);
            tr.innerHTML=`<td>${{i.is_dir?'📁':'📄'}} ${{i.name}}</td><td>${{i.size}}</td><td>${{i.ext||'DIR'}}</td>
            <td>${{!i.is_dir?`<a href="/api/download?path=${{encodeURIComponent(i.path)}}">DL</a>`:''}} 
            <span style="color:red;cursor:pointer" onclick="del(event,'${{i.path}}')">X</span></td>`;
            b.appendChild(tr);
        }});
    }}

    async function loadStats() {{
        view('stats');
        const b = document.getElementById('stats-body');
        b.innerHTML = 'Calculating...';
        const res = await fetch('/api/stats');
        const d = await res.json();
        
        let html = `<div style="padding:15px; border:1px solid #eee; border-radius:5px; margin-bottom:20px; background:#f9f9f9">
            <strong>PyAV Status:</strong> ${{d.av_status}}
        </div>`;
        
        if(d.limit_warning) {{
            html += `<div style="padding:10px; background:#ffebeb; color:red; border:1px solid red; border-radius:5px; margin-bottom:20px">
                ⚠️ <strong>WARNING:</strong> App Code is large! Vercel limit is usually 250MB (unzipped).
            </div>`;
        }}
        
        d.storage.forEach(s => {{
            // Scale bar relative to 500MB for visualization
            let pct = Math.min(100, (s.bytes / (500*1024*1024)) * 100);
            html += `
            <div class="stat-card">
                <div style="display:flex; justify-content:space-between">
                    <strong>${{s.label}}</strong>
                    <span>${{s.fmt}}</span>
                </div>
                <div class="progress"><div class="bar" style="width:${{pct}}%"></div></div>
            </div>`;
        }});
        b.innerHTML = html;
    }}

    async function show(p){{
        const res=await fetch(`/api/view?path=${{encodeURIComponent(p)}}`);
        const d=await res.json();
        document.getElementById('m-text').textContent=d.content||d.err;
        document.getElementById('modal').style.display='flex';
    }}
    
    async function del(e,p){{ e.stopPropagation(); if(confirm('Del '+p+'?')) {{ await fetch(`/api/delete?path=${{encodeURIComponent(p)}}`); nav(cur); }} }}
    function up(){{ let p=cur.split('/').filter(x=>x); p.pop(); nav('/'+p.join('/')); }}
    function ref(){{ nav(cur); }}
    document.getElementById('addr').onkeypress=e=>{{if(e.key==='Enter')nav(e.target.value)}};
    
    // Term
    const tin=document.getElementById('term-in'), tout=document.getElementById('term-out');
    tin.onkeypress=async e=>{{
        if(e.key==='Enter'){{
            const c=tin.value; tin.value='';
            tout.appendChild(document.createTextNode('\\n$ '+c+'\\n'));
            if(c==='clear'){{ tout.innerHTML=''; return; }}
            const res=await fetch(`/api/shell?cmd=${{encodeURIComponent(c)}}`);
            const d=await res.json();
            tout.appendChild(document.createTextNode(d.out||''));
            tout.scrollTop=tout.scrollHeight;
        }}
    }};
    nav(cur);
</script></body></html>
    """
