from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
import os
import json

app = FastAPI()

def get_directory_tree(path):
    try:
        # Get only the immediate children to keep the JSON small
        # We handle expansion via clicking (re-fetching or simple visibility)
        entries = os.listdir(path)
        tree = []
        for entry in sorted(entries):
            full_path = os.path.join(path, entry)
            is_dir = os.path.isdir(full_path)
            tree.append({
                "name": entry,
                "path": full_path,
                "type": "folder" if is_dir else "file"
            })
        return tree
    except Exception as e:
        return [{"name": f"Error: {str(e)}", "type": "error"}]

@app.get("/", response_class=HTMLResponse)
def read_root(target: str = Query(None)):
    # If no target is provided, show the actual Linux root "/"
    # Change target to os.getcwd() if you only want to see your app files
    root_to_show = target if target else "/"
    
    # Get current contents of the target folder
    contents = get_directory_tree(root_to_show)
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vercel System Explorer</title>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #fafafa; }}
            .container {{ max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            .item {{ padding: 8px; border-bottom: 1px solid #eee; display: flex; align-items: center; }}
            .item:hover {{ background: #f0f7ff; }}
            .folder {{ font-weight: bold; color: #0070f3; cursor: pointer; text-decoration: none; }}
            .file {{ color: #666; }}
            .breadcrumb {{ margin-bottom: 20px; font-size: 1.1em; }}
            .breadcrumb a {{ color: #0070f3; text-decoration: none; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>System Explorer</h1>
            <div class="breadcrumb">
                <strong>Path:</strong> {root_to_show} 
                {f' | <a href="/?target={os.path.dirname(root_to_show.rstrip("/")) or "/"}">⬆️ Up one level</a>' if root_to_show != "/" else ""}
            </div>
            
            <div id="file-list">
                {"".join([
                    f'<div class="item">'
                    f'{"📁" if i["type"]=="folder" else "📄"} '
                    f'{"<a class=\'folder\' href=\'/?target=" + i["path"] + "\'>" + i["name"] + "</a>" if i["type"]=="folder" else "<span class=\'file\'>" + i["name"] + "</span>"}'
                    f'</div>' 
                    for i in contents
                ])}
            </div>
        </div>
    </body>
    </html>
    """
    return html_content
