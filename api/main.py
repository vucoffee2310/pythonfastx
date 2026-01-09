from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import sys
import ctypes
import pkg_resources
from datetime import datetime

# ==========================================
# 1. RUNTIME & LIBRARY LINKAGE
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
        for f in os.listdir(lib_path):
            if f.startswith("lib") and ".so" in f:
                ctypes.CDLL(os.path.join(lib_path, f))
    except: pass

# ==========================================
# 2. APP & UTILS
# ==========================================
app = FastAPI()

def get_pyav_status():
    try:
        import av
        return f"✅ PyAV {av.__version__} (Codecs: {len(av.codecs_available)})"
    except ImportError as e:
        return f"❌ Import Error: {str(e)}"
    except Exception as e:
        return f"❌ Runtime Error: {str(e)}"

@app.get("/api/sys-info")
def get_sys_info():
    """Returns Python environment details."""
    installed_packages = sorted([f"{d.project_name}=={d.version}" for d in pkg_resources.working_set])
    
    return {
        "python_version": sys.version,
        "executable": sys.executable,
        "sys_path": sys.path,  # <--- THIS IS WHERE PYTHON LOOKS FOR SITE-PACKAGES
        "environment_vars": dict(os.environ),
        "installed_packages": installed_packages,
        "pyav_status": get_pyav_status()
    }

@app.get("/api/list")
def list_directory(path: str = "/"):
    if not os.path.exists(path): raise HTTPException(404, "Path not found")
    try:
        items = []
        with os.scandir(path) as entries:
            sorted_entries = sorted(entries, key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in sorted_entries:
                try:
                    stat = os.stat(entry.path)
                    items.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": entry.is_dir(),
                        "size": stat.st_size if not entry.is_dir() else "-",
                        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                        "ext": os.path.splitext(entry.path)[1].lower()
                    })
                except: continue
        return {"current_path": path, "items": items}
    except Exception as e:
        raise HTTPException(403, str(e))

@app.get("/api/view")
def view_file(path: str):
    try:
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary File"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except Exception as e: return {"error": str(e)}

@app.get("/api/download")
def download_file(path: str):
    return FileResponse(path, filename=os.path.basename(path))

@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Vercel System Explorer</title>
    <style>
        body {{ margin: 0; font-family: sans-serif; height: 100vh; display: flex; flex-direction: column; }}
        header {{ padding: 10px; border-bottom: 1px solid #ccc; display: flex; gap: 10px; background: #f4f4f4; }}
        #address-bar {{ flex-grow: 1; padding: 5px; font-family: monospace; }}
        main {{ display: flex; flex-grow: 1; overflow: hidden; }}
        aside {{ width: 250px; background: #fafafa; border-right: 1px solid #ddd; padding: 10px; overflow-y: auto; }}
        #content {{ flex-grow: 1; overflow-y: auto; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 10px; background: #eee; position: sticky; top: 0; }}
        td {{ padding: 8px; border-bottom: 1px solid #eee; white-space: nowrap; }}
        tr.can-open {{ cursor: pointer; }}
        tr:hover {{ background: #eef; }}
        .btn {{ cursor: pointer; padding: 5px 10px; border: 1px solid #ccc; background: white; border-radius: 4px; display: block; margin-bottom: 5px; text-decoration: none; color: black; font-size: 13px; }}
        .btn:hover {{ background: #ddd; }}
        .sys-info-panel {{ background: #222; color: #0f0; padding: 15px; font-family: monospace; white-space: pre-wrap; display: none; height: 100%; overflow: auto; }}
        
        #preview-modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100; }}
        .modal-inner {{ background: white; width: 90%; height: 90%; margin: 2% auto; display: flex; flex-direction: column; border-radius: 8px; overflow: hidden; }}
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
            <div style="font-weight:bold; margin-bottom:10px; font-size:12px; color:#666">EXPLORER</div>
            <a class="btn" onclick="navigateTo('/var/task')">📁 App Code (/var/task)</a>
            <a class="btn" onclick="navigateTo('/')">💻 Root (/)</a>
            <a class="btn" onclick="navigateTo('/var/lang/lib')">🐍 Python Libs (ReadOnly)</a>
            <a class="btn" onclick="navigateTo('{lib_path}')">📚 Custom Libs</a>
            <hr>
            <a class="btn" style="background:#eef" onclick="showSysInfo()">🐍 Python Env Info</a>
        </aside>
        
        <!-- File List -->
        <div id="content">
            <table>
                <thead><tr><th>Name</th><th>Size</th><th>Type</th><th>Act</th></tr></thead>
                <tbody id="list"></tbody>
            </table>
            <!-- Sys Info Panel (Hidden by default) -->
            <div id="sys-info" class="sys-info-panel"></div>
        </div>
    </main>

    <div id="preview-modal">
        <div class="modal-inner">
            <div style="padding:10px; background:#eee; display:flex; justify-content:space-between">
                <span id="p-title"></span>
                <button onclick="document.getElementById('preview-modal').style.display='none'">Close</button>
            </div>
            <pre id="p-body" style="padding:15px; overflow:auto; flex-grow:1"></pre>
        </div>
    </div>

<script>
    let currentPath = '/var/task';

    async function navigateTo(path) {{
        currentPath = path;
        document.getElementById('address-bar').value = path;
        document.getElementById('content').querySelector('table').style.display = 'table';
        document.getElementById('sys-info').style.display = 'none';
        
        const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
        const data = await res.json();
        
        const tbody = document.getElementById('list');
        tbody.innerHTML = '';
        data.items.forEach(i => {{
            const tr = document.createElement('tr');
            tr.className = (i.is_dir || i.ext=='.py' || i.ext=='.txt') ? 'can-open' : '';
            tr.ondblclick = () => i.is_dir ? navigateTo(i.path) : viewFile(i.path);
            tr.innerHTML = `<td>${{i.is_dir?'📁':'📄'}} ${{i.name}}</td><td>${{i.size}}</td><td>${{i.ext}}</td><td><a href="/api/download?path=${{encodeURIComponent(i.path)}}">⬇</a></td>`;
            tbody.appendChild(tr);
        }});
    }}

    async function showSysInfo() {{
        document.getElementById('content').querySelector('table').style.display = 'none';
        const panel = document.getElementById('sys-info');
        panel.style.display = 'block';
        panel.innerHTML = "Loading...";
        
        const res = await fetch('/api/sys-info');
        const data = await res.json();
        panel.innerHTML = "<strong>PYAV STATUS:</strong> " + data.pyav_status + "\\n\\n";
        panel.innerHTML += "<strong>SYS.PATH (Where Python looks):</strong>\\n" + JSON.stringify(data.sys_path, null, 2) + "\\n\\n";
        panel.innerHTML += "<strong>INSTALLED PACKAGES:</strong>\\n" + data.installed_packages.join('\\n');
    }}

    async function viewFile(path) {{
        const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
        const data = await res.json();
        document.getElementById('p-title').textContent = path;
        document.getElementById('p-body').textContent = data.content || data.error;
        document.getElementById('preview-modal').style.display = 'flex';
    }}

    function goUp() {{
        let p = currentPath.split('/').filter(x=>x); p.pop();
        navigateTo('/' + p.join('/'));
    }}
    function refresh() {{ navigateTo(currentPath); }}
    
    navigateTo(currentPath);
</script>
</body>
</html>
"""
