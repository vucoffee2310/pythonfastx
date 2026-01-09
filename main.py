from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import mimetypes
import time
from datetime import datetime

app = FastAPI()

def get_file_info(path):
    """Returns metadata for a file or folder."""
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
    """JSON API to get directory contents."""
    try:
        items = []
        for entry in sorted(os.listdir(path)):
            full_path = os.path.join(path, entry)
            try:
                items.append(get_file_info(full_path))
            except: continue # Skip files with permission issues
        return {"current_path": path, "items": items}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/api/view")
def view_file(path: str):
    """Returns raw text for previewing."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return {"content": f.read(200_000)} # Max 200kb
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download")
def download_file(path: str):
    return FileResponse(path, filename=os.path.basename(path))

@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Vercel File Explorer</title>
    <style>
        :root { --bg: #ffffff; --sidebar: #f5f5f7; --border: #e0e0e0; --accent: #0078d4; --hover: #edebe9; }
        body { margin: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        
        /* Top Bar */
        header { background: var(--sidebar); padding: 8px; border-bottom: 1px solid var(--border); display: flex; gap: 10px; align-items: center; }
        #address-bar { flex-grow: 1; padding: 5px 10px; border: 1px solid var(--border); border-radius: 4px; background: white; outline: none; }
        .nav-btn { cursor: pointer; padding: 5px 10px; border-radius: 4px; border: 1px solid transparent; background: none; }
        .nav-btn:hover { background: var(--hover); border: 1px solid var(--border); }

        /* Main Layout */
        main { display: flex; flex-grow: 1; overflow: hidden; }
        
        /* Sidebar */
        aside { width: 250px; background: var(--sidebar); border-right: 1px solid var(--border); padding: 10px; overflow-y: auto; }
        .bookmark { display: flex; align-items: center; padding: 6px; cursor: pointer; border-radius: 4px; font-size: 13px; }
        .bookmark:hover { background: var(--hover); }

        /* Content Area */
        #content { flex-grow: 1; background: var(--bg); overflow-y: auto; position: relative; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: left; padding: 10px; border-bottom: 1px solid var(--border); background: #fafafa; position: sticky; top: 0; }
        td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0; cursor: default; white-space: nowrap; }
        tr:hover { background-color: #f2f7ff; }
        tr.selected { background-color: #cce8ff !important; }
        
        /* Modal for Viewing */
        #preview-modal { display: none; position: fixed; top: 5%; left: 5%; width: 90%; height: 90%; background: #1e1e1e; color: #d4d4d4; z-index: 1000; border-radius: 8px; flex-direction: column; box-shadow: 0 0 50px rgba(0,0,0,0.5); }
        #preview-header { padding: 10px; background: #333; display: flex; justify-content: space-between; border-radius: 8px 8px 0 0; }
        #preview-body { flex-grow: 1; padding: 20px; overflow: auto; font-family: 'Consolas', monospace; white-space: pre; }
        .close-btn { cursor: pointer; color: white; border: none; background: #e81123; padding: 5px 15px; border-radius: 3px; }
    </style>
</head>
<body>

<header>
    <button class="nav-btn" onclick="goUp()">⬆ Up</button>
    <button class="nav-btn" onclick="refresh()">🔄 Refresh</button>
    <input type="text" id="address-bar" spellcheck="false">
</header>

<main>
    <aside>
        <div style="font-weight: bold; margin-bottom: 10px; font-size: 12px; color: #666;">QUICK ACCESS</div>
        <div class="bookmark" onclick="navigateTo('/')">📁 Computer (Root)</div>
        <div class="bookmark" onclick="navigateTo('/var/task')">🚀 App Code (/var/task)</div>
        <div class="bookmark" onclick="navigateTo('/tmp')">♻️ Temp (/tmp)</div>
        <div class="bookmark" onclick="navigateTo('/etc')">⚙️ System (/etc)</div>
    </aside>

    <section id="content">
        <table>
            <thead>
                <tr>
                    <th width="40%">Name</th>
                    <th width="20%">Date modified</th>
                    <th width="15%">Type</th>
                    <th width="15%">Size</th>
                    <th width="10%">Actions</th>
                </tr>
            </thead>
            <tbody id="file-table-body">
                <!-- Rows injected here -->
            </tbody>
        </table>
    </section>
</main>

<div id="preview-modal">
    <div id="preview-header">
        <span id="preview-title">File View</span>
        <button class="close-btn" onclick="closePreview()">X</button>
    </div>
    <div id="preview-body"></div>
</div>

<script>
    let currentPath = '/var/task';

    async function navigateTo(path) {
        currentPath = path;
        document.getElementById('address-bar').value = path;
        const resp = await fetch(`/api/list?path=${encodeURIComponent(path)}`);
        const data = await resp.json();
        
        if (data.detail) {
            alert("Error: " + data.detail);
            return;
        }

        const tbody = document.getElementById('file-table-body');
        tbody.innerHTML = '';

        data.items.forEach(item => {
            const tr = document.createElement('tr');
            tr.onclick = () => selectRow(tr);
            tr.ondblclick = () => item.is_dir ? navigateTo(item.path) : viewFile(item.path);
            
            const icon = item.is_dir ? '📁' : '📄';
            const type = item.is_dir ? 'File folder' : (item.ext || 'File');
            const size = item.is_dir ? '' : formatBytes(item.size);

            tr.innerHTML = `
                <td>${icon} ${item.name}</td>
                <td>${item.mtime}</td>
                <td>${type}</td>
                <td>${size}</td>
                <td>
                    ${!item.is_dir ? `<button onclick="downloadFile('${item.path}')">⬇️</button>` : ''}
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    function selectRow(row) {
        document.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
        row.classList.add('selected');
    }

    function goUp() {
        const parts = currentPath.split('/').filter(p => p);
        parts.pop();
        navigateTo('/' + parts.join('/'));
    }

    function refresh() { navigateTo(currentPath); }

    async function viewFile(path) {
        const resp = await fetch(`/api/view?path=${encodeURIComponent(path)}`);
        const data = await resp.json();
        if (data.error) {
            alert("Cannot preview binary or restricted file.");
            return;
        }
        document.getElementById('preview-body').textContent = data.content;
        document.getElementById('preview-title').textContent = "Viewing: " + path;
        document.getElementById('preview-modal').style.display = 'flex';
    }

    function closePreview() { document.getElementById('preview-modal').style.display = 'none'; }

    function downloadFile(path) {
        window.location.href = `/api/download?path=${encodeURIComponent(path)}`;
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // Handle Address Bar Enter
    document.getElementById('address-bar').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') navigateTo(e.target.value);
    });

    // Initial Load
    navigateTo(currentPath);
</script>
</body>
</html>
    """
