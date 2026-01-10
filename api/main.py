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
# 1. RUNTIME CONFIGURATION (Libs & Tools)
# ==========================================
# Get the absolute path to this file (e.g., /var/task/api/main.py)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the project root (e.g., /var/task)
project_root = os.path.dirname(current_dir)

# Define custom paths
lib_path = os.path.join(project_root, "lib")
bin_path = os.path.join(project_root, "bin")

# --- A. Link Custom Executables (Tree, JQ, etc) ---
if os.path.exists(bin_path):
    # Add to PATH so 'subprocess.run("tree")' works without full path
    current_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bin_path}:{current_path}"
    
    # Ensure they are executable (permissions can be lost during zip/unzip)
    try:
        subprocess.run(f"chmod -R +x {bin_path}", shell=True)
    except: pass

# --- B. Link Custom Libraries (FFmpeg/PyAV) ---
if os.path.exists(lib_path):
    # Add to Python Path
    sys.path.append(lib_path)
    
    # Add to Linux Linker Path
    current_ld = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = f"{lib_path}:{current_ld}"

    # Pre-load shared objects to help PyAV find them
    libs_order = ["libavutil", "libswresample", "libswscale", "libavcodec", "libavformat", "libavdevice", "libavfilter"]
    try:
        available_files = os.listdir(lib_path)
        for lib_prefix in libs_order:
            for filename in available_files:
                if filename.startswith(lib_prefix) and ".so" in filename:
                    try: ctypes.CDLL(os.path.join(lib_path, filename))
                    except: pass
    except: pass

# ==========================================
# 2. PYAV IMPORT CHECK
# ==========================================
av_status = "Initializing..."
try:
    import av
    codecs = len(av.codecs_available)
    av_status = f"✅ <strong>PyAV {av.__version__} Ready</strong> | Codecs: {codecs}"
except ImportError as e:
    av_status = f"❌ <strong>Import Failed:</strong> {e}"
except Exception as e:
    av_status = f"❌ <strong>Error:</strong> {e}"

# ==========================================
# 3. FASTAPI APPLICATION
# ==========================================
app = FastAPI()

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

# --- API ROUTES ---

@app.get("/api/list")
def list_dir(path: str = "/"):
    if not os.path.exists(path): raise HTTPException(404, "Path not found")
    try:
        items = []
        with os.scandir(path) as entries:
            # Sort: Directories first, then files
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                i = get_file_info(e.path)
                if i: items.append(i)
        return {"current_path": path, "items": items, "av_status": av_status}
    except Exception as e: raise HTTPException(403, str(e))

@app.get("/api/shell")
def shell_exec(cmd: str):
    """Executes bash commands using the updated PATH."""
    if not cmd: return {"output": "", "code": 0}
    try:
        # Run with timeout to prevent freezing the lambda
        res = subprocess.run(
            cmd, 
            shell=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True, 
            timeout=5, 
            cwd=os.getcwd()
        )
        return {"output": res.stdout, "code": res.returncode}
    except subprocess.TimeoutExpired:
        return {"output": "Error: Command timed out (Max 5s)", "code": 124}
    except Exception as e:
        return {"output": f"Execution Error: {str(e)}", "code": 1}

@app.get("/api/delete")
def delete_file(path: str):
    if not os.path.exists(path): return {"error": "File not found"}
    try:
        if os.path.isdir(path): os.rmdir(path) # Only works if empty
        else: os.remove(path)
        return {"status": "✅ Deleted"}
    except OSError as e:
        if e.errno == 30: return {"error": "🔒 READ-ONLY FILESYSTEM: Cannot delete files here."}
        if e.errno == 13: return {"error": "⛔ PERMISSION DENIED"}
        return {"error": f"❌ Error: {e.strerror}"}

@app.get("/api/view")
def view_file(path: str):
    if not os.path.exists(path): return {"error": "Not found"}
    try:
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary file cannot be viewed"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except Exception as e: return {"error": str(e)}

@app.get("/api/download")
def download_file(path: str):
    if not os.path.exists(path): raise HTTPException(404)
    return FileResponse(path, filename=os.path.basename(path))

@app.get("/api/test-permissions")
def test_permissions():
    """Checks writable locations."""
    results = []
    for p in ["/var/task", "/var/lang", "/opt", "/tmp", bin_path]:
        try:
            t = os.path.join(p, ".test")
            with open(t, 'w') as f: f.write('x')
            os.remove(t)
            results.append({"path": p, "status": "✅ WRITABLE", "color": "green"})
        except OSError as e:
            msg = "🔒 READ-ONLY" if e.errno == 30 else f"⛔ {e.strerror}"
            results.append({"path": p, "status": msg, "color": "red"})
    return results

@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Vercel OS Explorer</title>
    <style>
        :root {{ --bg:#fff; --sidebar:#f7f7f7; --accent:#0070f3; --term-bg:#1e1e1e; --term-text:#0f0; }}
        * {{ box-sizing: border-box; }}
        body {{ margin:0; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; height:100vh; display:flex; flex-direction:column; overflow:hidden; }}
        
        /* Header */
        header {{ padding:10px; background:#f4f4f4; border-bottom:1px solid #ddd; display:flex; gap:10px; }}
        #addr {{ flex-grow:1; padding:6px; font-family:monospace; border:1px solid #ccc; border-radius:4px; }}
        button {{ cursor:pointer; padding:5px 12px; background:#fff; border:1px solid #ccc; border-radius:4px; }}
        button:hover {{ background:#eee; }}

        /* Layout */
        main {{ display:flex; flex-grow:1; overflow:hidden; }}
        aside {{ width:240px; background:var(--sidebar); border-right:1px solid #ddd; padding:15px; display:flex; flex-direction:column; }}
        
        .nav-item {{ padding:8px; cursor:pointer; font-size:13px; color:#444; border-radius:4px; margin-bottom:2px; }}
        .nav-item:hover {{ background:rgba(0,0,0,0.05); color:#000; }}
        .nav-item.active {{ background:white; color:var(--accent); border:1px solid #ddd; font-weight:bold; }}

        #views {{ flex-grow:1; position:relative; background:var(--bg); }}
        .view-panel {{ position:absolute; inset:0; display:none; flex-direction:column; overflow:hidden; }}
        .view-panel.active {{ display:flex; }}

        /* Explorer View */
        #file-list {{ flex-grow:1; overflow-y:auto; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th {{ text-align:left; padding:10px; background:#fafafa; border-bottom:1px solid #eee; position:sticky; top:0; }}
        td {{ padding:8px 10px; border-bottom:1px solid #f5f5f5; white-space:nowrap; }}
        tr.can-open {{ cursor:pointer; }}
        tr:hover {{ background:#f0f7ff; }}
        .action-btn {{ font-size:11px; text-decoration:none; padding:2px 6px; border:1px solid #ccc; border-radius:3px; color:#333; margin-right:5px; }}

        /* Terminal View */
        #term-out {{ flex-grow:1; background:var(--term-bg); color:#ccc; padding:15px; font-family:'Consolas',monospace; font-size:13px; overflow-y:auto; white-space:pre-wrap; }}
        #term-bar {{ display:flex; background:#333; padding:10px; }}
        #term-prompt {{ color:var(--term-text); font-family:monospace; margin-right:10px; font-weight:bold; }}
        #term-in {{ flex-grow:1; background:transparent; border:none; color:white; font-family:monospace; outline:none; }}

        /* Modal */
        #modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:999; align-items:center; justify-content:center; }}
        .modal-card {{ background:white; width:90%; height:90%; display:flex; flex-direction:column; padding:20px; border-radius:8px; }}
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
        <div style="font-size:11px; font-weight:bold; color:#888; margin-bottom:10px">LOCATIONS</div>
        <div class="nav-item" onclick="nav('/var/task')">📁 App Code</div>
        <div class="nav-item" onclick="nav('/')">💻 Root</div>
        <div class="nav-item" onclick="nav('/tmp')">♻️ Temp (Writable)</div>
        <div class="nav-item" onclick="nav('{bin_path}')">🛠 Bin Tools</div>
        <div class="nav-item" onclick="nav('{lib_path}')">📚 Libs</div>
        
        <div style="font-size:11px; font-weight:bold; color:#888; margin:20px 0 10px">MODES</div>
        <div id="btn-exp" class="nav-item active" onclick="setView('explorer')">📂 File Explorer</div>
        <div id="btn-term" class="nav-item" onclick="setView('terminal')">💻 Terminal Shell</div>
        
        <div style="font-size:11px; font-weight:bold; color:#888; margin:20px 0 10px">STATUS</div>
        <div style="font-size:11px; padding:5px; background:#fff; border:1px solid #eee; border-radius:4px">
            {av_status}
        </div>
        <div class="nav-item" onclick="checkPerms()" style="margin-top:10px; color:blue">🛡 Check Perms</div>
    </aside>

    <div id="views">
        <!-- EXPLORER -->
        <div id="explorer" class="view-panel active">
            <div id="file-list">
                <table>
                    <thead><tr><th>Name</th><th>Size</th><th>Type</th><th>Actions</th></tr></thead>
                    <tbody id="file-body"></tbody>
                </table>
            </div>
        </div>

        <!-- TERMINAL -->
        <div id="terminal" class="view-panel">
            <div id="term-out">
Vercel Web Shell v1.0
Environment: Linux (Amazon Linux 2)
Custom Tools: tree, jq, busybox available in path.
---------------------------------------------------
</div>
            <div id="term-bar">
                <span id="term-prompt">user@vercel:~$</span>
                <input type="text" id="term-in" autocomplete="off" placeholder="ls -la, tree, whoami...">
            </div>
        </div>
    </div>
</main>

<div id="modal">
    <div class="modal-card">
        <div style="display:flex; justify-content:space-between; margin-bottom:10px">
            <b id="modal-title">File View</b>
            <button onclick="document.getElementById('modal').style.display='none'">Close</button>
        </div>
        <pre id="modal-text" style="flex-grow:1; overflow:auto; background:#f4f4f4; padding:10px; font-family:monospace"></pre>
    </div>
</div>

<script>
    let curPath = '/var/task';
    const textExts = ['.py','.txt','.sh','.json','.md','.log','.xml','.yml','.env'];

    function setView(id) {{
        document.querySelectorAll('.view-panel').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        document.getElementById(id === 'explorer' ? 'btn-exp' : 'btn-term').classList.add('active');
        if(id === 'terminal') document.getElementById('term-in').focus();
    }}

    // --- EXPLORER FUNCTIONS ---
    async function nav(path) {{
        setView('explorer');
        curPath = path;
        document.getElementById('addr').value = path;
        const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
        const data = await res.json();
        
        const tbody = document.getElementById('file-body');
        tbody.innerHTML = '';
        
        data.items.forEach(item => {{
            const tr = document.createElement('tr');
            const canOpen = item.is_dir || textExts.includes(item.ext);
            if (canOpen) tr.classList.add('can-open');
            
            tr.ondblclick = () => item.is_dir ? nav(item.path) : view(item.path);
            
            tr.innerHTML = `
                <td>${{item.is_dir?'📁':'📄'}} ${{item.name}}</td>
                <td>${{item.size}}</td>
                <td>${{item.ext || 'DIR'}}</td>
                <td>
                    ${{!item.is_dir ? `<a class="action-btn" href="/api/download?path=${{encodeURIComponent(item.path)}}">DL</a>` : ''}}
                    <span class="action-btn" style="color:red; cursor:pointer" onclick="del(event, '${{item.path}}')">DEL</span>
                </td>
            `;
            tbody.appendChild(tr);
        }});
    }}

    async function view(path) {{
        const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
        const d = await res.json();
        document.getElementById('modal-title').innerText = path;
        document.getElementById('modal-text').innerText = d.content || d.error;
        document.getElementById('modal').style.display = 'flex';
    }}

    async function del(e, path) {{
        e.stopPropagation();
        if(!confirm('Delete: ' + path + '?')) return;
        const res = await fetch(`/api/delete?path=${{encodeURIComponent(path)}}`);
        const d = await res.json();
        if(d.error) alert(d.error); else {{ nav(curPath); }}
    }}

    function goUp() {{ let p=curPath.split('/').filter(x=>x); p.pop(); nav('/'+p.join('/')); }}
    function refresh() {{ nav(curPath); }}
    document.getElementById('addr').onkeypress = e => {{ if(e.key==='Enter') nav(e.target.value); }};

    // --- TERMINAL FUNCTIONS ---
    const termIn = document.getElementById('term-in');
    const termOut = document.getElementById('term-out');
    
    termIn.addEventListener('keypress', async (e) => {{
        if(e.key === 'Enter') {{
            const cmd = termIn.value;
            termIn.value = '';
            log(`user@vercel:~$ ${{cmd}}`);
            if(cmd === 'clear') {{ termOut.innerHTML=''; return; }}
            
            try {{
                const res = await fetch(`/api/shell?cmd=${{encodeURIComponent(cmd)}}`);
                const d = await res.json();
                const color = d.code === 0 ? '#ddd' : '#ff5555';
                log(d.output || (d.code===0 ? '' : 'Error'), color);
            }} catch(err) {{ log('Network Error', 'red'); }}
        }}
    }});

    function log(text, color='#ccc') {{
        const d = document.createElement('div');
        d.textContent = text;
        d.style.color = color;
        termOut.appendChild(d);
        termOut.scrollTop = termOut.scrollHeight;
    }}
    
    async function checkPerms() {{
        const res = await fetch('/api/test-permissions');
        const d = await res.json();
        let msg = "FILESYSTEM PERMISSIONS:\\n";
        d.forEach(i => msg += `${{i.path}} -> ${{i.status}}\\n`);
        alert(msg);
    }}

    // Init
    nav('/var/task');
</script>
</body>
</html>
    """
