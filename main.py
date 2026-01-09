from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import mimetypes
from datetime import datetime

app = FastAPI()

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
            full_path = os.path.join(path, entry)
            try:
                items.append(get_file_info(full_path))
            except: continue 
        return {"current_path": path, "items": items}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/api/view")
def view_file(path: str):
    try:
        # Basic binary check
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024):
                return {"error": "Binary file"}
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download")
def download_file(path: str):
    return FileResponse(path, filename=os.path.basename(path))

@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Vercel Windows Explorer</title>
    <style>
        :root { --bg: #ffffff; --sidebar: #f5f5f7; --border: #e0e0e0; --accent: #0078d4; --hover: #edebe9; }
        body { margin: 0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; color: #333; }
        
        header { background: var(--sidebar); padding: 8px; border-bottom: 1px solid var(--border); display: flex; gap: 10px; align-items: center; }
        #address-bar { flex-grow: 1; padding: 5px 10px; border: 1px solid var(--border); border-radius: 4px; outline: none; }
        .nav-btn { cursor: pointer; padding: 5px 10px; border: 1px solid transparent; background: none; border-radius: 4px; }
        .nav-btn:hover { background: var(--hover); border: 1px solid var(--border); }

        main { display: flex; flex-grow: 1; overflow: hidden; }
        aside { width: 240px; background: var(--sidebar); border-right: 1px solid var(--border); padding: 10px; }
        .bookmark { display: flex; align-items: center; padding: 8px; cursor: pointer; border-radius: 4px; font-size: 13px; }
        .bookmark:hover { background: var(--hover); }

        #content { flex-grow: 1; background: var(--bg); overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
        th { text-align: left; padding: 10px; border-bottom: 1px solid var(--border); background: #fafafa; position: sticky; top: 0; }
        td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        
        /* Cursor logic */
        tr.can-open { cursor: pointer; }
        tr.cannot-open { cursor: default; }
        tr:hover { background-color: #f2f7ff; }
        tr.selected { background-color: #cce8ff; }

        .btn-dl { cursor: pointer; border: none; background: #0078d4; color: white; border-radius: 3px; padding: 2px 8px; }
        
        #preview-modal { display: none; position: fixed; top: 5%; left: 5%; width: 90%; height: 90%; background: #1e1e1e; color: #d4d4d4; z-index: 1000; border-radius: 8px; flex-direction: column; box-shadow: 0 0 40px rgba(0,0,0,0.5); }
        #preview-header { padding: 12px; background: #333; display: flex; justify-content: space-between; border-radius: 8px 8px 0 0; align-items: center; }
        #preview-body { flex-grow: 1; padding: 20px; overflow: auto; font-family: 'Consolas', monospace; white-space: pre; font-size: 14px; }
        .close-btn { cursor: pointer; background: #e81123; color: white; border: none; padding: 5px 15px; border-radius: 3px; }
    </style>
</head>
<body>

<header>
    <button class="nav-btn" onclick="goUp()">⬆ Up</button>
    <input type="text" id="address-bar">
    <button class="nav-btn" onclick="refresh()">🔄</button>
</header>

<main>
    <aside>
        <div class="bookmark" onclick="navigateTo('/')">💻 System Root</div>
        <div class="bookmark" onclick="navigateTo('/var/task')">🚀 App Code</div>
        <div class="bookmark" onclick="navigateTo('/tmp')">♻️ Temp Folder</div>
    </aside>

    <section id="content">
        <table>
            <thead>
                <tr>
                    <th width="40%">Name</th>
                    <th width="25%">Date modified</th>
                    <th width="15%">Type</th>
                    <th width="10%">Size</th>
                    <th width="10%"></th>
                </tr>
            </thead>
            <tbody id="file-table-body"></tbody>
        </table>
    </section>
</main>

<div id="preview-modal">
    <div id="preview-header">
        <span id="preview-title"></span>
        <button class="close-btn" onclick="closePreview()">Close</button>
    </div>
    <div id="preview-body"></div>
</div>

<script>
    let currentPath = '/var/task';
    const TEXT_EXTS = ['.py', '.js', '.json', '.txt', '.html', '.css', '.md', '.env', '.yml', '.yaml', '.sh', '.log'];

    async function navigateTo(path) {
        currentPath = path;
        document.getElementById('address-bar').value = path;
        const resp = await fetch(`/api/list?path=${encodeURIComponent(path)}`);
        const data = await resp.json();
        
        const tbody = document.getElementById('file-table-body');
        tbody.innerHTML = '';

        data.items.forEach(item => {
            const tr = document.createElement('tr');
            
            // Interaction logic
            const isText = TEXT_EXTS.includes(item.ext);
            const canOpen = item.is_dir || isText;

            // Set the cursor based on whether the file can be opened
            tr.className = canOpen ? 'can-open' : 'cannot-open';
            
            tr.onclick = () => {
                document.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
                tr.classList.add('selected');
            };

            tr.ondblclick = () => {
                if (item.is_dir) navigateTo(item.path);
                else if (isText) viewFile(item.path);
            };

            tr.innerHTML = `
                <td>${item.is_dir ? '📁' : '📄'} ${item.name}</td>
                <td>${item.mtime}</td>
                <td>${item.is_dir ? 'Folder' : (item.ext.toUpperCase() || 'File')}</td>
                <td>${item.is_dir ? '' : formatBytes(item.size)}</td>
                <td style="text-align: right;">
                    ${!item.is_dir ? `<button class="btn-dl" onclick="downloadFile(event, '${item.path}')">Download</button>` : ''}
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    async function viewFile(path) {
        const resp = await fetch(`/api/view?path=${encodeURIComponent(path)}`);
        const data = await resp.json();
        if (data.error) return alert("Binary or inaccessible file.");
        
        document.getElementById('preview-body').textContent = data.content;
        document.getElementById('preview-title').textContent = path;
        document.getElementById('preview-modal').style.display = 'flex';
    }

    function downloadFile(event, path) {
        event.stopPropagation(); // Prevent row click
        window.location.href = `/api/download?path=${encodeURIComponent(path)}`;
    }

    function formatBytes(b) {
        if (b === 0) return '0 B';
        const i = Math.floor(Math.log(b) / Math.log(1024));
        return (b / Math.pow(1024, i)).toFixed(1) + ' ' + ['B', 'KB', 'MB', 'GB'][i];
    }

    function goUp() {
        const p = currentPath.split('/').filter(x => x);
        p.pop();
        navigateTo('/' + p.join('/'));
    }

    function refresh() { navigateTo(currentPath); }
    function closePreview() { document.getElementById('preview-modal').style.display = 'none'; }

    document.getElementById('address-bar').onkeypress = (e) => {
        if (e.key === 'Enter') navigateTo(e.target.value);
    };

    navigateTo(currentPath);
</script>
</body>
</html>
    """
