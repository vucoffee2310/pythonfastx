from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import mimetypes
import sys

app = FastAPI()

def get_directory_tree(path):
    try:
        entries = os.listdir(path)
        tree = []
        for entry in sorted(entries):
            full_path = os.path.normpath(os.path.join(path, entry))
            is_dir = os.path.isdir(full_path)
            tree.append({
                "name": entry,
                "path": full_path,
                "type": "folder" if is_dir else "file"
            })
        return tree
    except Exception as e:
        return [{"name": f"Access Denied: {str(e)}", "type": "error"}]

@app.get("/download")
def download_file(path: str):
    if not os.path.exists(path) or os.path.isdir(path):
        raise HTTPException(status_code=404, detail="File not found")
    
    mime_type, _ = mimetypes.guess_type(path)
    return FileResponse(path, media_type=mime_type, filename=os.path.basename(path))

@app.get("/", response_class=HTMLResponse)
def read_root(target: str = Query(None)):
    # 1. Determine current view
    root_to_show = target if target else "/"
    contents = get_directory_tree(root_to_show)
    
    # 2. Explicitly find Vercel-specific paths for the "Bookmarks"
    bookmarks = {
        "Root": "/",
        "App Code (/var/task)": "/var/task",
        "Python Path": os.path.dirname(sys.executable),
        "Temp (Writeable)": "/tmp"
    }
    
    # Look for anything starting with 'vercel' in the root
    try:
        for item in os.listdir('/'):
            if 'vercel' in item.lower():
                bookmarks[f"Vercel Internal ({item})"] = f"/{item}"
    except:
        pass

    # 3. Build Bookmark HTML
    bookmark_html = "".join([
        f'<a class="btn" href="/?target={path}">{name}</a>' 
        for name, path in bookmarks.items()
    ])

    # 4. Build File List HTML
    rows = ""
    for item in contents:
        icon = "📁" if item["type"] == "folder" else "📄"
        if item["type"] == "folder":
            link = f'<a class="folder" href="/?target={item["path"]}">{item["name"]}</a>'
            actions = ""
        elif item["type"] == "file":
            link = f'<a class="file" href="/download?path={item["path"]}" target="_blank">{item["name"]}</a>'
            actions = f'<a class="download-btn" href="/download?path={item["path"]}" download>Download</a>'
        else:
            link = f'<span class="error-text">{item["name"]}</span>'
            actions = ""

        rows += f'<div class="item"><span class="icon">{icon}</span><span class="name">{link}</span><span class="actions">{actions}</span></div>'

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vercel Internal Explorer</title>
        <style>
            body {{ font-family: -apple-system, system-ui, sans-serif; padding: 30px; background: #fafafa; color: #333; }}
            .container {{ max-width: 1000px; margin: auto; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 5px 20px rgba(0,0,0,0.08); }}
            .bookmarks {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 25px; padding: 15px; background: #f0f2f5; border-radius: 8px; }}
            .btn {{ padding: 6px 12px; background: #0070f3; color: white; text-decoration: none; border-radius: 5px; font-size: 13px; font-weight: 500; }}
            .btn:hover {{ background: #0051ad; }}
            .breadcrumb {{ font-family: monospace; background: #222; color: #00ff00; padding: 12px; border-radius: 6px; margin-bottom: 20px; word-break: break-all; }}
            .item {{ display: flex; align-items: center; padding: 10px; border-bottom: 1px solid #eee; }}
            .icon {{ margin-right: 12px; }}
            .name {{ flex-grow: 1; }}
            .folder {{ color: #0070f3; font-weight: bold; text-decoration: none; }}
            .file {{ color: #444; text-decoration: none; }}
            .download-btn {{ font-size: 11px; border: 1px solid #0070f3; color: #0070f3; padding: 3px 7px; border-radius: 4px; text-decoration: none; }}
            .error-text {{ color: #999; font-style: italic; font-size: 0.9em; }}
            .back-link {{ display: block; margin-bottom: 15px; color: #666; text-decoration: none; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Vercel System Explorer</h1>
            
            <div class="bookmarks">
                <strong>Jump to:</strong> {bookmark_html}
            </div>

            <div class="breadcrumb">
                $ cd {root_to_show}
            </div>
            
            {f'<a class="back-link" href="/?target={os.path.dirname(root_to_show.rstrip("/")) or "/"}">⬆️ Up one level</a>' if root_to_show != "/" else ""}

            <div id="file-list">
                {rows}
            </div>
        </div>
    </body>
    </html>
    """
    return html_content
