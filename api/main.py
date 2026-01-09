from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import sys
import ctypes
import mimetypes
import shutil
import pkg_resources
from datetime import datetime

# ==========================================
# 1. RUNTIME CONFIGURATION (The "Glue")
# ==========================================
# This section tells Vercel where to find the FFmpeg libraries we compiled.

# Get the absolute path to this file (e.g., /var/task/api/main.py)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the project root (e.g., /var/task)
project_root = os.path.dirname(current_dir)
# Path to our custom library folder (e.g., /var/task/lib)
lib_path = os.path.join(project_root, "lib")

# Pre-load libraries using ctypes to help PyAV find them
if os.path.exists(lib_path):
    # Add to system path for python imports
    sys.path.append(lib_path)
    
    # Add to LD_LIBRARY_PATH for the Linux Linker
    if "LD_LIBRARY_PATH" in os.environ:
        os.environ["LD_LIBRARY_PATH"] += f":{lib_path}"
    else:
        os.environ["LD_LIBRARY_PATH"] = lib_path

    # Manually load the core FFmpeg libs in dependency order
    libs_to_load = ["libavutil", "libswresample", "libswscale", "libavcodec", "libavformat", "libavdevice", "libavfilter"]
    try:
        # Scan dir for actual filenames (e.g., libavcodec.so.58)
        available_files = os.listdir(lib_path)
        for lib_prefix in libs_to_load:
            for filename in available_files:
                if filename.startswith(lib_prefix) and ".so" in filename:
                    full_path = os.path.join(lib_path, filename)
                    try:
                        ctypes.CDLL(full_path)
                    except: pass
    except: pass

# ==========================================
# 2. PYAV IMPORT & HEALTH CHECK
# ==========================================
av_status_msg = "Initializing..."
try:
    import av
    # Try to access internal FFmpeg data
    codecs = sorted([c.name for c in av.codecs_available])
    av_status_msg = f"✅ <strong>PyAV {av.__version__} Installed</strong><br>"
    av_status_msg += f"<small>Linked to: {lib_path}</small><br>"
    av_status_msg += f"<small>Codecs found: {len(codecs)}</small>"
except ImportError as e:
    av_status_msg = f"❌ <strong>PyAV Import Failed</strong><br><small>{str(e)}</small>"
except Exception as e:
    av_status_msg = f"❌ <strong>Runtime Error</strong><br><small>{str(e)}</small>"

# ==========================================
# 3. FASTAPI APP
# ==========================================
app = FastAPI()

def get_file_info(path):
    try:
        stat = os.stat(path)
        return {
            "name": os.path.basename(path),
            "path": path,
            "is_dir": os.path.isdir(path),
            "size": stat.st_size if not os.path.isdir(path) else "-",
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            "ext": os.path.splitext(path)[1].lower()
        }
    except: return None

# --- API ROUTES ---

@app.get("/api/list")
def list_directory(path: str = "/"):
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Path not found")
    try:
        items = []
        with os.scandir(path) as entries:
            sorted_entries = sorted(entries, key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in sorted_entries:
                info = get_file_info(entry.path)
                if info: items.append(info)
        return {"current_path": path, "items": items, "av_status": av_status_msg}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/api/view")
def view_file(path: str):
    if not os.path.exists(path): return {"error": "File not found"}
    try:
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary file cannot be viewed."}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except Exception as e: return {"error": str(e)}

@app.get("/api/download")
def download_file(path: str):
    if not os.path.exists(path) or os.path.isdir(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=os.path.basename(path))

@app.get("/api/sys-info")
def get_sys_info():
    """Returns detailed python env info."""
    packages = sorted([f"{d.project_name}=={d.version}" for d in pkg_resources.working_set])
    return {
        "python": sys.version,
        "sys_path": sys.path,
        "packages": packages,
        "env": dict(os.environ)
    }

@app.get("/api/test-permissions", response_class=HTMLResponse)
def test_permissions():
    """Tries to write files to prove Read-Only status."""
    folders = ["/var/task", "/var/lang", "/opt", "/usr/local", "/tmp"]
    rows = ""
    for folder in folders:
        status, color = "", ""
        test_file = os.path.join(folder, "write_test.txt")
        try:
            if not os.path.exists(folder):
                status, color = "⚠️ Not Found", "orange"
            else:
                with open(test_file, "w") as f: f.write("test")
                os.remove(test_file)
                status, color = "✅ WRITABLE", "green"
        except OSError as e:
            if e.errno == 30: status, color = "🔒 READ-ONLY (Errno 30)", "red"
            elif e.errno == 13: status, color = "⛔ PERMISSION DENIED", "red"
            else: status, color = f"❌ {e.strerror}", "red"
        
        rows += f"<tr><td style='font-family:monospace'>{folder}</td><td style='color:{color}; font-weight:bold'>{status}</td></tr>"

    return f"""
    <html><body style='font-family:sans-serif; padding:40px; background:#f4f4f4'>
    <div style='background:white; padding:30px; border-radius:8px; max-width:600px; margin:auto; box-shadow:0 4px 10px rgba(0,0,0,0.1)'>
    <a href='/' style='text-decoration:none; color:#0070f3'>&larr; Back</a>
    <h2>Filesystem Permission Test</h2>
    <table style='width:100%; text-align:left; border-collapse:collapse'>
    <tr style='background:#eee'><th style='padding:10px'>Directory</th><th>Result</th></tr>
    {rows}</table></div></body></html>
    """

# --- FRONTEND ---

@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Vercel System Explorer</title>
    <style>
        :root {{ --bg: #ffffff; --sidebar: #f0f0f5; --border: #e1e1e6; --accent: #0070f3; --text: #333; }}
        body {{ margin: 0; font-family: -apple-system, system-ui, sans-serif; height: 100vh; display: flex; flex-direction: column; color: var(--text); }}
        
        header {{ background: var(--bg); padding: 12px; border-bottom: 1px solid var(--border); display: flex; gap: 10px; }}
        #address-bar {{ flex-grow: 1; padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; font-family: monospace; }}
        
        main {{ display: flex; flex-grow: 1; overflow: hidden; }}
        aside {{ width: 260px; background: var(--sidebar); border-right: 1px solid var(--border); padding: 15px; display: flex; flex-direction: column; overflow-y: auto; }}
        
        .bookmark {{ padding: 8px; cursor: pointer; border-radius: 6px; font-size: 13px; color: #444; margin-bottom: 2px; }}
        .bookmark:hover {{ background: rgba(0,0,0,0.05); color: #000; }}
        .status-box {{ font-size: 12px; background: white; border: 1px solid var(--border); padding: 10px; border-radius: 8px; margin-bottom: 20px; }}
        
        #content {{ flex-grow: 1; background: var(--bg); overflow-y: auto; position: relative; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 12px 15px; border-bottom: 1px solid var(--border); background: #fafafa; position: sticky; top: 0; }}
        td {{ padding: 10px 15px; border-bottom: 1px solid #f5f5f5; white-space: nowrap; }}
        
        tr.can-open {{ cursor: pointer; }}
        tr:hover {{ background-color: #f4faff; }}
        tr.selected {{ background-color: #e6f3ff; }}
        .btn-dl {{ border: 1px solid var(--accent); color: var(--accent); border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer; background:white; text-decoration:none; }}
        
        #info-panel, #preview-modal {{ display: none; position: absolute; inset: 0; background: white; z-index: 20; padding: 20px; overflow: auto; }}
        #preview-modal {{ background: rgba(0,0,0,0.6); display: none; align-items: center; justify-content: center; }}
        .modal-card {{ background: #1e1e1e; width: 90%; height: 90%; border-radius: 8px; display: flex; flex-direction: column; color: #ccc; }}
        .close-btn {{ background: #e81123; color: white; border: none; padding: 5px 12px; border-radius: 4px; cursor: pointer; }}
    </style>
</head>
<body>

<header>
    <button onclick="goUp()">⬆</button>
    <input type="text" id="address-bar">
    <button onclick="refresh()">🔄</button>
</header>

<main>
    <aside>
        <div class="status-box" id="av-status">Loading Status...</div>
        
        <div style="font-weight:bold; font-size:11px; color:#999; margin-bottom:5px">LOCATIONS</div>
        <div class="bookmark" onclick="navigateTo('/var/task')">🚀 App Code (/var/task)</div>
        <div class="bookmark" onclick="navigateTo('/')">💻 System Root (/)</div>
        <div class="bookmark" onclick="navigateTo('/tmp')">♻️ Temp (/tmp)</div>
        <div class="bookmark" onclick="navigateTo('{lib_path}')">📚 Custom Libs</div>
        
        <div style="font-weight:bold; font-size:11px; color:#999; margin:20px 0 5px">TOOLS</div>
        <div class="bookmark" onclick="window.location.href='/api/test-permissions'">🛑 Test Permissions</div>
        <div class="bookmark" onclick="showSysInfo()">🐍 Python Env Info</div>
    </aside>

    <section id="content">
        <div id="file-list">
            <table>
                <thead><tr><th>Name</th><th>Size</th><th>Type</th><th>Action</th></tr></thead>
                <tbody id="table-body"></tbody>
            </table>
        </div>
        
        <!-- System Info View -->
        <div id="info-panel">
            <button onclick="closeInfo()">Close</button>
            <pre id="sys-content" style="font-family:monospace"></pre>
        </div>
    </section>
</main>

<!-- Preview Modal -->
<div id="preview-modal">
    <div class="modal-card">
        <div style="padding:10px; background:#252526; display:flex; justify-content:space-between">
            <span id="preview-title"></span>
            <button class="close-btn" onclick="closePreview()">Close</button>
        </div>
        <pre id="preview-body" style="padding:20px; overflow:auto; margin:0"></pre>
    </div>
</div>

<script>
    let currentPath = '/var/task';
    const TEXT_EXTS = ['.py', '.js', '.json', '.txt', '.md', '.sh', '.log', '.env', '.yml'];

    async function navigateTo(path) {{
        currentPath = path;
        document.getElementById('address-bar').value = path;
        document.getElementById('file-list').style.display = 'block';
        document.getElementById('info-panel').style.display = 'none';
        
        try {{
            const resp = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
            const data = await resp.json();
            
            if(data.av_status) document.getElementById('av-status').innerHTML = data.av_status;
            
            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';
            
            data.items.forEach(item => {{
                const tr = document.createElement('tr');
                const isText = TEXT_EXTS.includes(item.ext);
                tr.className = (item.is_dir || isText) ? 'can-open' : '';
                
                tr.ondblclick = () => item.is_dir ? navigateTo(item.path) : viewFile(item.path);
                tr.onclick = () => {{ document.querySelectorAll('tr').forEach(r=>r.classList.remove('selected')); tr.classList.add('selected'); }};
                
                tr.innerHTML = `
                    <td>${{item.is_dir ? '📁' : '📄'}} ${{item.name}}</td>
                    <td>${{item.size}}</td>
                    <td>${{item.ext || 'Folder'}}</td>
                    <td>${{!item.is_dir ? `<a class="btn-dl" href="/api/download?path=${{encodeURIComponent(item.path)}}">DL</a>` : ''}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }} catch(e) {{ alert("Access Denied: " + e); }}
    }}

    async function viewFile(path) {{
        const resp = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
        const data = await resp.json();
        document.getElementById('preview-title').innerText = path;
        document.getElementById('preview-body').innerText = data.content || data.error;
        document.getElementById('preview-modal').style.display = 'flex';
    }}

    async function showSysInfo() {{
        document.getElementById('file-list').style.display = 'none';
        document.getElementById('info-panel').style.display = 'block';
        document.getElementById('sys-content').innerText = "Loading...";
        const resp = await fetch('/api/sys-info');
        const data = await resp.json();
        document.getElementById('sys-content').innerText = JSON.stringify(data, null, 2);
    }}

    function closePreview() {{ document.getElementById('preview-modal').style.display = 'none'; }}
    function closeInfo() {{ document.getElementById('info-panel').style.display = 'none'; document.getElementById('file-list').style.display = 'block'; }}
    function goUp() {{ let p=currentPath.split('/').filter(x=>x); p.pop(); navigateTo('/'+p.join('/')); }}
    function refresh() {{ navigateTo(currentPath); }}
    
    document.getElementById('address-bar').addEventListener('keypress', (e) => {{ if(e.key==='Enter') navigateTo(e.target.value); }});
    navigateTo(currentPath);
</script>
</body>
</html>
    """
