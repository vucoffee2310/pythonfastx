from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import sys
import mimetypes
from datetime import datetime

app = FastAPI()

# Check PyAV status
try:
    import av
    pyav_status = f"✅ PyAV Installed ({av.__version__})"
except ImportError as e:
    pyav_status = f"❌ PyAV Not Found: {str(e)}"

def get_file_info(path):
    stat = os.stat(path)
    return {
        "name": os.path.basename(path),
        "path": path,
        "is_dir": os.path.isdir(path),
        "size": stat.st_size if not os.path.isdir(path) else "-",
        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
        "ext": os.path.splitext(path)[1].lower()
    }

@app.get("/api/list")
def list_directory(path: str = "/"):
    try:
        items = []
        for entry in sorted(os.listdir(path)):
            full_path = os.path.normpath(os.path.join(path, entry))
            try: items.append(get_file_info(full_path))
            except: continue 
        return {"current_path": path, "items": items, "pyav": pyav_status}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/api/view")
def view_file(path: str):
    try:
        # Prevent opening large or binary files
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024): return {"error": "Binary"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except: return {"error": "Error"}

@app.get("/api/download")
def download_file(path: str):
    return FileResponse(path, filename=os.path.basename(path))

@app.get("/", response_class=HTMLResponse)
def index():
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Vercel Windows Explorer</title>
    <style>
        :root {{ --sidebar: #f5f5f7; --border: #e0e0e0; --accent: #0078d4; }}
        body {{ margin: 0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; }}
        header {{ background: var(--sidebar); padding: 8px; border-bottom: 1px solid var(--border); display: flex; gap: 10px; }}
        #status-bar {{ background: #222; color: #0f0; padding: 4px 15px; font-size: 11px; font-family: monospace; }}
        main {{ display: flex; flex-grow: 1; overflow: hidden; }}
        aside {{ width: 240px; background: var(--sidebar); border-right: 1px solid var(--border); padding: 10px; }}
        #content {{ flex-grow: 1; overflow-y: auto; background: white; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 10px; background: #fafafa; position: sticky; top: 0; border-bottom: 1px solid var(--border); }}
        td {{ padding: 8px 10px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }}
        tr.can-open {{ cursor: pointer; }}
        tr.can-open:hover {{ background: #f2f7ff; }}
        tr.cannot-open {{ cursor: default; }}
        .btn {{ padding: 2px 8px; background: var(--accent); color: white; border: none; border-radius: 3px; cursor: pointer; }}
        #address-bar {{ flex-grow: 1; padding: 4px; border: 1px solid #ccc; }}
        #preview-modal {{ display:none; position:fixed; top:5%; left:5%; width:90%; height:90%; background:#1e1e1e; color:#ddd; z-index:100; flex-direction:column; border-radius: 8px; }}
    </style>
</head>
<body>
    <div id="status-bar">PYTHON: {sys.executable} | STATUS: {pyav_status}</div>
    <header>
        <button onclick="goUp()">⬆ Up</button>
        <input type="text" id="address-bar" readonly>
    </header>
    <main>
        <aside>
            <div style="font-weight:bold; font-size:11px; color:#666; margin: 10px 0;">SYSTEM LOCATIONS</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/var/task')">📁 Project (/var/task)</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/vercel/path0')">⚙️ Runtime (/vercel/path0)</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/')">💻 Root (/)</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/tmp')">♻️ Temp (/tmp)</div>
        </aside>
        <div id="content">
            <table>
                <thead><tr><th>Name</th><th>Modified</th><th>Size</th><th>Action</th></tr></thead>
                <tbody id="file-list"></tbody>
            </table>
        </div>
    </main>
    <div id="preview-modal">
        <div style="padding:10px; background:#333; display:flex; justify-content:space-between">
            <span id="p-title"></span>
            <button onclick="document.getElementById('preview-modal').style.display='none'">Close</button>
        </div>
        <pre id="p-body" style="padding:20px; overflow:auto; flex-grow:1; margin:0; font-family:Consolas, monospace;"></pre>
    </div>
    <script>
        let currentPath = '/var/task';
        const TEXT_EXTS = ['.py', '.sh', '.json', '.txt', '.md', '.yml', '.env'];

        async function navigateTo(path) {{
            currentPath = path;
            document.getElementById('address-bar').value = path;
            const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
            const data = await res.json();
            const list = document.getElementById('file-list');
            list.innerHTML = '';
            
            data.items.forEach(item => {{
                const isText = TEXT_EXTS.includes(item.ext);
                const canOpen = item.is_dir || isText;
                const tr = document.createElement('tr');
                tr.className = canOpen ? 'can-open' : 'cannot-open';
                tr.ondblclick = () => {{
                    if (item.is_dir) navigateTo(item.path);
                    else if (isText) viewFile(item.path);
                }};
                tr.innerHTML = `
                    <td>${{item.is_dir ? '📁':'📄'}} ${{item.name}}</td>
                    <td>${{item.mtime}}</td>
                    <td>${{item.size}}</td>
                    <td>${{!item.is_dir ? `<button class="btn" onclick="location.href='/api/download?path='+encodeURIComponent('${{item.path}}')">DL</button>` : ''}}</td>
                `;
                list.appendChild(tr);
            }});
        }}

        async function viewFile(path) {{
            const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
            const data = await res.json();
            if (data.error) return alert("Cannot preview.");
            document.getElementById('p-title').innerText = path;
            document.getElementById('p-body').textContent = data.content;
            document.getElementById('preview-modal').style.display = 'flex';
        }}

        function goUp() {{
            let p = currentPath.split('/').filter(x=>x); p.pop();
            navigateTo('/' + p.join('/'));
        }}
        navigateTo(currentPath);
    </script>
</body>
</html>
"""
