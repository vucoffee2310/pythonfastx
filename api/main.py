from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import sys
import ctypes
import mimetypes
from datetime import datetime

# ==========================================
# 1. RUNTIME CONFIGURATION (The Critical Part)
# ==========================================
# We need to tell Python where to find the FFmpeg shared libraries (.so files)
# that we copied into the 'lib' folder during the 'avp.sh' build process.

# Get the absolute path to this file (e.g., /var/task/api/main.py)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the project root (e.g., /var/task)
project_root = os.path.dirname(current_dir)
# Path to our custom library folder
lib_path = os.path.join(project_root, "lib")

# Pre-load libraries using ctypes to help PyAV find them
if os.path.exists(lib_path):
    # Add to system path for good measure
    sys.path.append(lib_path)
    if "LD_LIBRARY_PATH" in os.environ:
        os.environ["LD_LIBRARY_PATH"] += f":{lib_path}"
    else:
        os.environ["LD_LIBRARY_PATH"] = lib_path

    # Manually load the core FFmpeg libs in order of dependency
    # This helps avoid "Shared object not found" errors
    libs_to_load = ["libavutil", "libswresample", "libswscale", "libavcodec", "libavformat", "libavdevice", "libavfilter"]
    
    # Scan the directory to find the actual .so filenames (e.g., libavcodec.so.58)
    available_files = os.listdir(lib_path)
    
    for lib_prefix in libs_to_load:
        for filename in available_files:
            if filename.startswith(lib_prefix) and ".so" in filename:
                full_path = os.path.join(lib_path, filename)
                try:
                    ctypes.CDLL(full_path)
                except Exception as e:
                    print(f"Warning: Could not pre-load {filename}: {e}")

# ==========================================
# 2. PYAV IMPORT & HEALTH CHECK
# ==========================================
av_status = "Initializing..."
try:
    import av
    # If import succeeds, try to access internal FFmpeg data
    codecs = sorted([c.name for c in av.codecs_available])
    av_version = av.__version__
    ffmpeg_version = av.library_versions
    
    av_status = f"✅ <strong>PyAV {av_version} Installed</strong><br>"
    av_status += f"<small>Linked to FFmpeg libraries in: {lib_path}</small><br>"
    av_status += f"<small>Available Codecs ({len(codecs)}): {', '.join(codecs[:10])}...</small>"
except ImportError as e:
    av_status = f"❌ <strong>PyAV Import Failed</strong><br><small>{str(e)}</small><br><small>Checked path: {lib_path}</small>"
except Exception as e:
    av_status = f"❌ <strong>Runtime Error</strong><br><small>{str(e)}</small>"

# ==========================================
# 3. FASTAPI APP & EXPLORER LOGIC
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
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            "ext": os.path.splitext(path)[1].lower()
        }
    except FileNotFoundError:
        return None

@app.get("/api/list")
def list_directory(path: str = "/"):
    """JSON API to get directory contents."""
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Path not found")
        
    try:
        items = []
        # Sort: Folders first, then files
        with os.scandir(path) as entries:
            sorted_entries = sorted(entries, key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in sorted_entries:
                try:
                    info = get_file_info(entry.path)
                    if info: items.append(info)
                except: continue
        return {"current_path": path, "items": items, "av_status": av_status}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

@app.get("/api/view")
def view_file(path: str):
    """Returns raw text for previewing code/logs."""
    if not os.path.exists(path):
        return {"error": "File not found"}
    try:
        # Security check: Read first 1kb to check for binary null bytes
        with open(path, 'rb') as f:
            if b'\x00' in f.read(1024):
                return {"error": "Binary file cannot be viewed as text."}
        
        # If safe, read text
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read(200_000) # Limit to 200kb
            return {"content": content}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download")
def download_file(path: str):
    """Force download a file."""
    if not os.path.exists(path) or os.path.isdir(path):
        raise HTTPException(status_code=404, detail="File not found")
    
    filename = os.path.basename(path)
    return FileResponse(path, filename=filename)

@app.get("/", response_class=HTMLResponse)
def index():
    """The Main Explorer UI."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vercel System Explorer</title>
    <style>
        :root {{ --bg: #ffffff; --sidebar: #f0f0f5; --border: #e1e1e6; --accent: #0070f3; --hover: #f7f7f9; --text: #333; }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; height: 100vh; display: flex; flex-direction: column; color: var(--text); }}
        
        /* HEADER */
        header {{ background: var(--bg); padding: 12px; border-bottom: 1px solid var(--border); display: flex; gap: 10px; align-items: center; }}
        #address-bar {{ flex-grow: 1; padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; outline: none; background: #fbfbfb; font-family: monospace; font-size: 13px; }}
        #address-bar:focus {{ border-color: var(--accent); background: #fff; }}
        .nav-btn {{ cursor: pointer; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border); background: white; font-size: 13px; transition: all 0.2s; }}
        .nav-btn:hover {{ background: var(--hover); border-color: #ccc; }}

        /* MAIN LAYOUT */
        main {{ display: flex; flex-grow: 1; overflow: hidden; }}
        
        /* SIDEBAR */
        aside {{ width: 260px; background: var(--sidebar); border-right: 1px solid var(--border); padding: 15px; display: flex; flex-direction: column; overflow-y: auto; }}
        .section-title {{ font-size: 11px; font-weight: 700; color: #888; margin: 15px 0 5px 0; text-transform: uppercase; letter-spacing: 0.5px; }}
        .bookmark {{ display: flex; align-items: center; padding: 8px 10px; cursor: pointer; border-radius: 6px; font-size: 13px; color: #444; text-decoration: none; margin-bottom: 2px; }}
        .bookmark:hover {{ background: rgba(0,0,0,0.05); color: #000; }}
        .bookmark i {{ margin-right: 8px; }}

        /* PYAV STATUS BOX */
        .status-box {{ font-size: 12px; background: white; border: 1px solid var(--border); padding: 10px; border-radius: 8px; margin-bottom: 10px; line-height: 1.4; }}
        
        /* FILE CONTENT */
        #content {{ flex-grow: 1; background: var(--bg); overflow-y: auto; display: flex; flex-direction: column; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }}
        th {{ text-align: left; padding: 12px 15px; border-bottom: 1px solid var(--border); background: #fafafa; position: sticky; top: 0; color: #666; font-weight: 600; z-index: 10; }}
        td {{ padding: 10px 15px; border-bottom: 1px solid #f5f5f5; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }}
        
        /* CURSORS & INTERACTIONS */
        tr {{ transition: background 0.1s; }}
        tr.can-open {{ cursor: pointer; }}
        tr.cannot-open {{ cursor: default; }}
        tr:hover {{ background-color: #f4faff; }}
        tr.selected {{ background-color: #e6f3ff; }}
        
        .icon {{ display: inline-block; width: 20px; text-align: center; margin-right: 8px; }}
        .btn-dl {{ background: transparent; border: 1px solid var(--accent); color: var(--accent); border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer; opacity: 0; transition: opacity 0.2s; }}
        tr:hover .btn-dl {{ opacity: 1; }}
        .btn-dl:hover {{ background: var(--accent); color: white; }}

        /* PREVIEW MODAL */
        #preview-modal {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 1000; align-items: center; justify-content: center; backdrop-filter: blur(2px); }}
        .modal-card {{ background: #1e1e1e; width: 90%; height: 85%; border-radius: 12px; display: flex; flex-direction: column; box-shadow: 0 20px 50px rgba(0,0,0,0.5); overflow: hidden; }}
        .modal-header {{ padding: 12px 20px; background: #252526; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; }}
        .modal-title {{ color: #ccc; font-family: monospace; font-size: 14px; }}
        .close-btn {{ background: #e81123; color: white; border: none; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-weight: bold; }}
        #preview-body {{ flex-grow: 1; padding: 20px; overflow: auto; color: #d4d4d4; font-family: 'Consolas', 'Monaco', monospace; font-size: 13px; line-height: 1.5; white-space: pre; }}

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
        <div class="status-box" id="av-status">
            Loading System Status...
        </div>

        <div class="section-title">Favorites</div>
        <div class="bookmark" onclick="navigateTo('/var/task')">🚀 App Code (/var/task)</div>
        <div class="bookmark" onclick="navigateTo('/')">💻 System Root (/)</div>
        <div class="bookmark" onclick="navigateTo('/tmp')">♻️ Temp (/tmp)</div>
        <div class="bookmark" onclick="navigateTo('{lib_path}')">📚 Custom Libs</div>
    </aside>

    <section id="content">
        <table>
            <thead>
                <tr>
                    <th width="45%">Name</th>
                    <th width="20%">Date modified</th>
                    <th width="15%">Type</th>
                    <th width="10%">Size</th>
                    <th width="10%">Action</th>
                </tr>
            </thead>
            <tbody id="file-table-body">
                <!-- Rows injected via JS -->
            </tbody>
        </table>
    </section>
</main>

<!-- Modal -->
<div id="preview-modal">
    <div class="modal-card">
        <div class="modal-header">
            <span class="modal-title" id="preview-title">Filename.py</span>
            <button class="close-btn" onclick="closePreview()">Close</button>
        </div>
        <div id="preview-body">Loading...</div>
    </div>
</div>

<script>
    let currentPath = '/var/task';
    // Extensions we treat as text/code
    const TEXT_EXTS = ['.py', '.js', '.json', '.txt', '.html', '.css', '.md', '.env', '.yml', '.yaml', '.sh', '.log', '.ini', '.cfg'];

    async function navigateTo(path) {{
        currentPath = path;
        document.getElementById('address-bar').value = path;
        
        try {{
            const resp = await fetch(`/api/list?path=${{encodeURIComponent(path)}}`);
            if (!resp.ok) throw new Error(await resp.text());
            const data = await resp.json();
            
            // Update Status Box
            if(data.av_status) document.getElementById('av-status').innerHTML = data.av_status;

            const tbody = document.getElementById('file-table-body');
            tbody.innerHTML = '';

            data.items.forEach(item => {{
                const tr = document.createElement('tr');
                const isText = TEXT_EXTS.includes(item.ext);
                const canOpen = item.is_dir || isText;
                
                tr.className = canOpen ? 'can-open' : 'cannot-open';
                
                // Click to select
                tr.onclick = () => {{
                    document.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
                    tr.classList.add('selected');
                }};

                // Double click to action
                tr.ondblclick = () => {{
                    if (item.is_dir) navigateTo(item.path);
                    else if (isText) viewFile(item.path);
                }};

                const icon = item.is_dir ? '📁' : '📄';
                const typeStr = item.is_dir ? 'File folder' : (item.ext.toUpperCase().replace('.', '') + ' File');

                tr.innerHTML = `
                    <td><span class="icon">${{icon}}</span>${{item.name}}</td>
                    <td>${{item.mtime}}</td>
                    <td>${{typeStr}}</td>
                    <td>${{item.size}}</td>
                    <td>
                        ${{!item.is_dir ? `<button class="btn-dl" onclick="downloadFile(event, '${{item.path}}')">Download</button>` : ''}}
                    </td>
                `;
                tbody.appendChild(tr);
            }});
        }} catch (err) {{
            alert("Error accessing path: " + err.message);
        }}
    }}

    async function viewFile(path) {{
        const modal = document.getElementById('preview-modal');
        const body = document.getElementById('preview-body');
        const title = document.getElementById('preview-title');
        
        modal.style.display = 'flex';
        body.textContent = "Loading...";
        title.textContent = path;

        const resp = await fetch(`/api/view?path=${{encodeURIComponent(path)}}`);
        const data = await resp.json();
        
        if (data.error) body.textContent = "Error: " + data.error;
        else body.textContent = data.content;
    }}

    function closePreview() {{
        document.getElementById('preview-modal').style.display = 'none';
    }}

    function downloadFile(e, path) {{
        e.stopPropagation(); // Stop row selection
        window.location.href = `/api/download?path=${{encodeURIComponent(path)}}`;
    }}

    function goUp() {{
        // Basic path manipulation
        const parts = currentPath.split('/').filter(p => p);
        parts.pop();
        navigateTo('/' + parts.join('/'));
    }}

    function refresh() {{ navigateTo(currentPath); }}

    // Address bar enter key
    document.getElementById('address-bar').addEventListener('keypress', (e) => {{
        if (e.key === 'Enter') navigateTo(e.target.value);
    }});

    // Initial load
    navigateTo(currentPath);
</script>
</body>
</html>
    """
