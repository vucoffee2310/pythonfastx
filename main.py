from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import os
import mimetypes

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
        return [{"name": f"Error: {str(e)}", "type": "error"}]

@app.get("/download")
def download_file(path: str):
    """Endpoint to download or view a specific file."""
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    
    if os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Cannot download a directory")

    # Determine media type (text/plain, image/png, etc.)
    mime_type, _ = mimetypes.guess_type(path)
    
    # Return the file. 
    # 'inline' opens in browser, 'attachment' forces download.
    return FileResponse(
        path, 
        media_type=mime_type, 
        filename=os.path.basename(path)
    )

@app.get("/", response_class=HTMLResponse)
def read_root(target: str = Query(None)):
    root_to_show = target if target else "/"
    contents = get_directory_tree(root_to_show)
    
    # HTML generation
    rows = ""
    for item in contents:
        icon = "📁" if item["type"] == "folder" else "📄"
        
        if item["type"] == "folder":
            link = f'<a class="folder" href="/?target={item["path"]}">{item["name"]}</a>'
            actions = ""
        elif item["type"] == "file":
            # Link to open in browser
            link = f'<a class="file" href="/download?path={item["path"]}" target="_blank">{item["name"]}</a>'
            # Link to force download
            actions = f'<a class="download-btn" href="/download?path={item["path"]}" download>Download</a>'
        else:
            link = f'<span style="color:red">{item["name"]}</span>'
            actions = ""

        rows += f"""
        <div class="item">
            <span class="icon">{icon}</span>
            <span class="name">{link}</span>
            <span class="actions">{actions}</span>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vercel File Explorer</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; padding: 40px; background: #f5f5f7; color: #1d1d1f; }}
            .container {{ max-width: 900px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
            h1 {{ margin-top: 0; font-size: 24px; }}
            .breadcrumb {{ margin-bottom: 20px; padding: 10px; background: #f0f0f2; border-radius: 6px; font-family: monospace; overflow-wrap: break-word; }}
            .item {{ display: flex; align-items: center; padding: 10px; border-bottom: 1px solid #eee; }}
            .item:hover {{ background: #f9f9fb; }}
            .icon {{ margin-right: 12px; font-size: 1.2em; }}
            .name {{ flex-grow: 1; }}
            .folder {{ color: #0071e3; font-weight: 600; text-decoration: none; }}
            .file {{ color: #1d1d1f; text-decoration: none; }}
            .file:hover {{ text-decoration: underline; }}
            .actions {{ margin-left: 20px; }}
            .download-btn {{ 
                font-size: 12px; 
                background: #0071e3; 
                color: white; 
                padding: 4px 8px; 
                border-radius: 4px; 
                text-decoration: none; 
            }}
            .back-link {{ display: inline-block; margin-bottom: 15px; color: #0071e3; text-decoration: none; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>System Explorer</h1>
            <div class="breadcrumb">
                <strong>Current Path:</strong> {root_to_show}
            </div>
            
            {f'<a class="back-link" href="/?target={os.path.dirname(root_to_show.rstrip("/")) or "/"}">← Back Up</a>' if root_to_show != "/" else ""}

            <div id="file-list">
                {rows}
            </div>
        </div>
    </body>
    </html>
    """
    return html_content
