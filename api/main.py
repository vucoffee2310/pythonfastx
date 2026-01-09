from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import mimetypes
import sys
from datetime import datetime

app = FastAPI()

# Check PyAV status
try:
    import av
    pyav_status = f"✅ PyAV Installed ({av.__version__})"
except ImportError:
    pyav_status = "❌ PyAV Not Found"

def get_file_info(path):
    stat = os.stat(path)
    return {
        "name": os.path.basename(path),
        "path": path,
        "is_dir": os.path.isdir(path),
        "size": stat.st_size if not os.path.isdir(path) else "-",
        "mtime": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
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
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except: return {"error": "Inaccessible"}

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
    <title>Vercel Explorer</title>
    <style>
        :root {{ --accent: #0078d4; }}
        body {{ margin: 0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
        #status-bar {{ background: #222; color: #0f0; padding: 5px 15px; font-size: 12px; font-family: monospace; }}
        header {{ background: #f3f3f3; padding: 8px; border-bottom: 1px solid #ccc; display: flex; gap: 10px; }}
        main {{ display: flex; flex-grow: 1; overflow: hidden; }}
        aside {{ width: 220px; background: #fafafa; border-right: 1px solid #ddd; padding: 10px; }}
        #content {{ flex-grow: 1; overflow-y: auto; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 10px; background: #eee; position: sticky; top: 0; }}
        td {{ padding: 8px 10px; border-bottom: 1px solid #eee; white-space: nowrap; }}
        
        tr.can-open {{ cursor: pointer; }}
        tr.can-open:hover {{ background: #e8f2ff; }}
        tr.cannot-open {{ cursor: default; }}
        
        .btn-dl {{ cursor: pointer; background: var(--accent); color: white; border: none; padding: 3px 8px; border-radius: 3px; font-size: 11px; }}
        #preview-modal {{ display:none; position:fixed; top:5%; left:5%; width:90%; height:90%; background:#1e1e1e; color:#ddd; z-index:100; flex-direction:column; border-radius: 8px; box-shadow: 0 0 30px rgba(0,0,0,0.5); }}
    </style>
</head>
<body>
    <div id="status-bar">Vercel Runtime Status: {pyav_status}</div>
    <header>
        <button onclick="goUp()">⬆ Up</button>
        <input type="text" id="address" style="flex-grow:1" readonly>
    </header>
    <main>
        <aside>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/var/task')">📁 App Root (/var/task)</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/')">💻 System Root (/)</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/tmp')">♻️ Temp Folder</div>
        </aside>
        <div id="content">
            <table>
                <thead><tr><th width="40%">Name</th><th width="20%">Size</th><th width="20%">Type</th><th width="20%">Action</th></tr></thead>
                <tbody id="list"></tbody>
            </table>
        </div>
    </main>
    <div id="preview-modal">
        <div style="padding:10px; background:#333; display:flex; justify-content:space-between">
            <span id="p-title"></span>
            <button onclick="document.getElementById('preview-modal').style.display='none'">Close</button>
        </div>
        <pre id="p-body" style="padding:20px; overflow:auto; flex-grow:1; margin:0; font-family: monospace;"></pre>
    </div>
    <script>
        let currentPath = '/var/task';
        const TEXT_EXTS = ['.py', '.sh', '.json', '.txt', '.md', '.yml', '.yaml', '.env'];

        async function navigateTo(path) {{
            currentPath = path;
            document.getElementById('address').value = path;
            const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
            const data = await res.json();
            const list = document.getElementById('list');
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
                    <td>${{item.size}}</td>
                    <td>${{item.is_dir ? 'Folder' : (item.ext.toUpperCase() || 'File')}}</td>
                    <td>${{!item.is_dir ? `<button class="btn-dl" onclick="location.href='/api/download?path='+encodeURIComponent('${{item.path}}')">Download</button>` : ''}}</td>
                `;
                list.appendChild(tr);
            }});
        }}

        async function viewFile(path) {{
            const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
            const data = await res.json();
            if (data.error) return alert("Binary or inaccessible file.");
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
