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

# ==========================================
# 1. RUNTIME CONFIGURATION
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
lib_path = os.path.join(project_root, "lib")

if os.path.exists(lib_path):
    sys.path.append(lib_path)
    if "LD_LIBRARY_PATH" in os.environ:
        os.environ["LD_LIBRARY_PATH"] += f":{lib_path}"
    else:
        os.environ["LD_LIBRARY_PATH"] = lib_path

    # Pre-load FFmpeg libs
    try:
        libs = ["libavutil", "libswresample", "libswscale", "libavcodec", "libavformat", "libavdevice", "libavfilter"]
        found = os.listdir(lib_path)
        for l in libs:
            for f in found:
                if f.startswith(l) and ".so" in f:
                    try: ctypes.CDLL(os.path.join(lib_path, f))
                    except: pass
    except: pass

# ==========================================
# 2. APP & ROUTES
# ==========================================
app = FastAPI()

# --- PyAV Status ---
av_status = "Init..."
try:
    import av
    av_status = f"✅ PyAV {av.__version__} (Codecs: {len(av.codecs_available)})"
except Exception as e:
    av_status = f"❌ {str(e)}"

# --- Helper ---
def get_file_info(path):
    try:
        s = os.stat(path)
        return {
            "name": os.path.basename(path),
            "path": path,
            "is_dir": os.path.isdir(path),
            "size": s.st_size if not os.path.isdir(path) else "-",
            "mtime": datetime.fromtimestamp(s.st_mtime).strftime('%Y-%m-%d %H:%M'),
            "ext": os.path.splitext(path)[1].lower()
        }
    except: return None

@app.get("/api/list")
def list_dir(path: str = "/"):
    if not os.path.exists(path): raise HTTPException(404, "Not found")
    items = []
    try:
        with os.scandir(path) as entries:
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                i = get_file_info(e.path)
                if i: items.append(i)
        return {"current_path": path, "items": items, "av_status": av_status}
    except Exception as e: raise HTTPException(403, str(e))

@app.get("/api/shell")
def shell(cmd: str):
    """Run bash commands."""
    try:
        res = subprocess.run(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
            text=True, timeout=5, cwd=os.getcwd()
        )
        return {"output": res.stdout, "code": res.returncode}
    except subprocess.TimeoutExpired: return {"output": "Timeout", "code": 124}
    except Exception as e: return {"output": str(e), "code": 1}

@app.get("/api/view")
def view(path: str):
    try:
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary file"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except Exception as e: return {"error": str(e)}

@app.get("/api/download")
def download(path: str):
    if not os.path.exists(path): raise HTTPException(404)
    return FileResponse(path, filename=os.path.basename(path))

@app.get("/api/delete")
def delete(path: str):
    try:
        os.remove(path)
        return {"status": "Deleted"}
    except OSError as e: return {"error": f"OS Error {e.errno}: {e.strerror}"}

@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Vercel Console</title>
    <style>
        :root {{ --bg:#fff; --sidebar:#f4f4f4; --accent:#0070f3; --term-bg:#1e1e1e; --term-text:#0f0; }}
        body {{ margin:0; font-family:sans-serif; height:100vh; display:flex; flex-direction:column; overflow:hidden; }}
        header {{ padding:10px; background:#eee; border-bottom:1px solid #ccc; display:flex; gap:10px; }}
        #addr {{ flex-grow:1; padding:5px; font-family:monospace; }}
        
        main {{ display:flex; flex-grow:1; }}
        aside {{ width:240px; background:var(--sidebar); padding:10px; border-right:1px solid #ddd; }}
        .btn {{ display:block; padding:8px; margin:2px 0; cursor:pointer; color:#333; font-size:13px; border-radius:4px; }}
        .btn:hover {{ background:#e0e0e0; }}
        
        #views {{ flex-grow:1; position:relative; }}
        .view-panel {{ position:absolute; inset:0; display:none; flex-direction:column; background:var(--bg); overflow:hidden; }}
        .active {{ display:flex; }}

        /* Explorer */
        #file-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        td, th {{ padding:8px; border-bottom:1px solid #eee; text-align:left; }}
        tr.can-open {{ cursor:pointer; }}
        tr:hover {{ background:#f0f7ff; }}
        
        /* Terminal */
        #term-output {{ flex-grow:1; background:var(--term-bg); color:#d4d4d4; padding:15px; font-family:'Consolas',monospace; font-size:13px; overflow-y:auto; white-space:pre-wrap; }}
        #term-input-line {{ display:flex; background:#333; padding:10px; }}
        #term-prompt {{ color:var(--term-text); margin-right:10px; font-family:monospace; font-weight:bold; }}
        #term-cmd {{ flex-grow:1; background:transparent; border:none; color:white; font-family:monospace; outline:none; font-size:13px; }}
        
        .success {{ color: #0f0; }} .error {{ color: #f44; }}
        
        /* Modal */
        #modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:99; align-items:center; justify-content:center; }}
        #modal-content {{ background:white; width:90%; height:90%; padding:20px; display:flex; flex-direction:column; }}
    </style>
</head>
<body>

<header>
    <button onclick="goUp()">⬆</button>
    <input type="text" id="addr">
    <button onclick="refresh()">🔄</button>
</header>

<main>
    <aside>
        <div style="font-size:11px; font-weight:bold; color:#888; margin-bottom:5px">NAVIGATION</div>
        <div class="btn" onclick="switchView('explorer'); nav('/var/task')">📁 App Code</div>
        <div class="btn" onclick="switchView('explorer'); nav('/')">💻 Root</div>
        <div class="btn" onclick="switchView('explorer'); nav('/tmp')">♻️ Temp</div>
        <div class="btn" onclick="switchView('explorer'); nav('{lib_path}')">📚 Libs</div>
        
        <div style="font-size:11px; font-weight:bold; color:#888; margin:20px 0 5px 0">TOOLS</div>
        <div class="btn" onclick="switchView('terminal')" style="background:#333; color:#fff">💻 Terminal Shell</div>
        <div class="btn" onclick="testPerms()">🔒 Check Perms</div>
    </aside>

    <div id="views">
        <!-- Explorer View -->
        <div id="explorer" class="view-panel active">
            <div style="overflow:auto; height:100%">
                <table id="file-table">
                    <thead><tr><th>Name</th><th>Size</th><th>Type</th><th>Action</th></tr></thead>
                    <tbody id="file-body"></tbody>
                </table>
            </div>
        </div>

        <!-- Terminal View -->
        <div id="terminal" class="view-panel">
            <div id="term-output">
                Welcome to Vercel Shell.
                OS: Linux (Read-Only Root)
                {av_status}
                -----------------------------------
            </div>
            <div id="term-input-line">
                <span id="term-prompt">vercel@lambda:~$</span>
                <input type="text" id="term-cmd" autocomplete="off" placeholder="Enter command (e.g., ls -la, pip list, whoami)">
            </div>
        </div>
    </div>
</main>

<div id="modal">
    <div id="modal-content">
        <div style="margin-bottom:10px"><button onclick="document.getElementById('modal').style.display='none'">Close</button></div>
        <pre id="modal-text" style="flex-grow:1; overflow:auto; background:#eee; padding:10px"></pre>
    </div>
</div>

<script>
    let curPath = '/var/task';
    const textExt = ['.py','.txt','.sh','.json','.md','.log','.env'];

    function switchView(id) {{
        document.querySelectorAll('.view-panel').forEach(e => e.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        if(id === 'terminal') document.getElementById('term-cmd').focus();
    }}

    // --- EXPLORER LOGIC ---
    async function nav(path) {{
        curPath = path;
        document.getElementById('addr').value = path;
        const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
        const data = await res.json();
        const b = document.getElementById('file-body');
        b.innerHTML = '';
        data.items.forEach(i => {{
            const tr = document.createElement('tr');
            const canOpen = i.is_dir || textExt.includes(i.ext);
            if(canOpen) tr.className = 'can-open';
            tr.ondblclick = () => i.is_dir ? nav(i.path) : view(i.path);
            
            tr.innerHTML = `
                <td>${{i.is_dir?'📁':'📄'}} ${{i.name}}</td>
                <td>${{i.size}}</td>
                <td>${{i.ext||'DIR'}}</td>
                <td>
                    ${{!i.is_dir ? `<a href="/api/download?path=${{encodeURIComponent(i.path)}}">DL</a> ` : ''}}
                    <button style="color:red;border:none;background:none;cursor:pointer" onclick="del(event, '${{i.path}}')">X</button>
                </td>`;
            b.appendChild(tr);
        }});
    }}

    async function view(path) {{
        const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
        const d = await res.json();
        showModal(d.content || d.error);
    }}
    
    async function del(e, path) {{
        e.stopPropagation();
        if(!confirm('Delete ' + path + '?')) return;
        const res = await fetch(`/api/delete?path=${{encodeURIComponent(path)}}`);
        const d = await res.json();
        alert(d.status || d.error);
        if(d.status) nav(curPath);
    }}
    
    function goUp() {{ let p=curPath.split('/').filter(x=>x); p.pop(); nav('/'+p.join('/')); }}
    function refresh() {{ nav(curPath); }}
    document.getElementById('addr').onkeypress = e => {{ if(e.key==='Enter') nav(e.target.value); }};

    // --- TERMINAL LOGIC ---
    const termCmd = document.getElementById('term-cmd');
    const termOut = document.getElementById('term-output');

    termCmd.addEventListener('keypress', async (e) => {{
        if(e.key === 'Enter') {{
            const cmd = termCmd.value;
            termCmd.value = '';
            log('vercel@lambda:~$ ' + cmd);
            
            if(cmd.trim() === 'clear') {{ termOut.innerHTML = ''; return; }}
            
            try {{
                const res = await fetch(`/api/shell?cmd=${{encodeURIComponent(cmd)}}`);
                const d = await res.json();
                if(d.code === 0) log(d.output, 'success');
                else log(d.output || ('Error ' + d.code), 'error');
            }} catch(err) {{
                log('Network Error', 'error');
            }}
            
            termOut.scrollTop = termOut.scrollHeight;
        }}
    }});

    function log(msg, type='') {{
        const div = document.createElement('div');
        div.textContent = msg;
        if(type) div.className = type;
        termOut.appendChild(div);
    }}

    function showModal(txt) {{
        document.getElementById('modal-text').textContent = txt;
        document.getElementById('modal').style.display = 'flex';
    }}
    
    async function testPerms() {{
        const res = await fetch('/api/test-permissions'); // reusing logic if present, else just list
        alert("Check Explorer View > /tmp for writable areas");
    }}

    // Init
    nav('/var/task');
</script>
</body>
</html>
    """
