from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import mimetypes
import sys
from datetime import datetime

app = FastAPI()

# Check if PyAV is installed
try:
    import av
    pyav_status = f"✅ PyAV Installed ({av.__version__}) - Path: {os.path.dirname(av.__file__)}"
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
    # I am using the Explorer UI we built previously
    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Vercel Explorer + PyAV</title>
    <style>
        body {{ margin: 0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
        header {{ background: #f3f3f3; padding: 10px; border-bottom: 1px solid #ccc; display: flex; align-items: center; gap: 10px; }}
        #status-bar {{ background: #333; color: white; padding: 5px 15px; font-size: 12px; font-family: monospace; }}
        main {{ display: flex; flex-grow: 1; overflow: hidden; }}
        aside {{ width: 220px; background: #fafafa; border-right: 1px solid #ddd; padding: 10px; }}
        #content {{ flex-grow: 1; overflow-y: auto; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ text-align: left; padding: 10px; background: #eee; position: sticky; top: 0; }}
        td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
        tr.can-open {{ cursor: pointer; }}
        tr.can-open:hover {{ background: #e8f2ff; }}
        .btn {{ padding: 3px 8px; font-size: 11px; cursor: pointer; }}
        #preview {{ display:none; position:fixed; top:5%; left:5%; width:90%; height:90%; background:#1e1e1e; color:#ddd; z-index:100; flex-direction:column; }}
    </style>
</head>
<body>
    <div id="status-bar">SYSTEM STATUS: {pyav_status}</div>
    <header>
        <button onclick="goUp()">⬆ Up</button>
        <input type="text" id="address" style="flex-grow:1" readonly>
    </header>
    <main>
        <aside>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/var/task')">📁 /var/task (App)</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/')">💻 / (Root)</div>
            <div style="cursor:pointer; padding:5px" onclick="navigateTo('/tmp')">♻️ /tmp</div>
        </aside>
        <div id="content">
            <table>
                <thead><tr><th>Name</th><th>Size</th><th>Type</th><th>Actions</th></tr></thead>
                <tbody id="list"></tbody>
            </table>
        </div>
    </main>
    <div id="preview">
        <div style="padding:10px; background:#333; display:flex; justify-content:space-between">
            <span id="p-title"></span>
            <button onclick="document.getElementById('preview').style.display='none'">Close</button>
        </div>
        <pre id="p-body" style="padding:20px; overflow:auto; flex-grow:1; margin:0"></pre>
    </div>
    <script>
        let currentPath = '/var/task';
        const TEXT_EXTS = ['.py', '.sh', '.json', '.txt', '.md', '.yml', '.env'];

        async function navigateTo(path) {{
            currentPath = path;
            document.getElementById('address').value = path;
            const res = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
            const data = await res.json();
            const list = document.getElementById('list');
            list.innerHTML = '';
            data.items.forEach(item => {{
                const isText = TEXT_EXTS.includes(item.ext);
                const tr = document.createElement('tr');
                if (item.is_dir || isText) tr.className = 'can-open';
                tr.ondblclick = () => item.is_dir ? navigateTo(item.path) : viewFile(item.path);
                tr.innerHTML = `
                    <td>${{item.is_dir ? '📁':'📄'}} ${{item.name}}</td>
                    <td>${{item.size}}</td>
                    <td>${{item.ext || (item.is_dir ? 'Folder' : 'File')}}</td>
                    <td><button class="btn" onclick="location.href='/api/download?path='+encodeURIComponent('${{item.path}}')">Download</button></td>
                `;
                list.appendChild(tr);
            }});
        }}
        async function viewFile(path) {{
            const res = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
            const data = await res.json();
            if (data.error) return alert("Binary file");
            document.getElementById('p-title').innerText = path;
            document.getElementById('p-body').textContent = data.content;
            document.getElementById('preview').style.display = 'flex';
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
