import os
import json
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

def get_directory_structure(rootdir):
    """
    Recursively builds a dictionary of the directory structure.
    """
    dir_structure = {}
    rootdir = rootdir.rstrip(os.sep)
    start = rootdir.rfind(os.sep) + 1
    
    dir_structure['name'] = os.path.basename(rootdir)
    dir_structure['type'] = 'folder'
    dir_structure['children'] = []

    try:
        if os.path.isdir(rootdir):
            for item in os.listdir(rootdir):
                path = os.path.join(rootdir, item)
                if os.path.isdir(path):
                    # Recursively call for subdirectories
                    dir_structure['children'].append(get_directory_structure(path))
                else:
                    dir_structure['children'].append({
                        "name": item,
                        "type": "file"
                    })
    except PermissionError:
        pass # Skip folders we can't access

    return dir_structure

@app.get("/", response_class=HTMLResponse)
def read_root():
    # 1. Get the current directory structure as a dictionary
    root_path = os.getcwd()
    structure = get_directory_structure(root_path)
    
    # 2. Convert to JSON string for the JavaScript to use
    json_structure = json.dumps(structure)

    # 3. Return HTML with embedded CSS and JS
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vercel Folder Tree</title>
        <style>
            body {{ font-family: monospace; background: #111; color: #eee; padding: 20px; }}
            ul {{ list-style-type: none; padding-left: 20px; }}
            li {{ margin: 5px 0; }}
            .folder {{ cursor: pointer; font-weight: bold; color: #f1d592; }}
            .folder::before {{ content: "📁 "; }}
            .file {{ color: #a6e22e; }}
            .file::before {{ content: "wc "; }}
            .nested {{ display: none; }}
            .active {{ display: block; }}
            .caret::before {{ content: "▶"; display: inline-block; margin-right: 6px; color: #888; transform: rotate(0deg); transition: transform 0.2s; }}
            .caret-down::before {{ transform: rotate(90deg); }}
        </style>
    </head>
    <body>
        <h2>📂 Server Root: {root_path}</h2>
        <div id="tree-root"></div>

        <script>
            const data = {json_structure};

            function createTree(container, node) {{
                const li = document.createElement('li');
                
                if (node.type === 'folder') {{
                    const span = document.createElement('span');
                    span.classList.add('folder', 'caret');
                    span.textContent = node.name;
                    li.appendChild(span);

                    const ul = document.createElement('ul');
                    ul.classList.add('nested');
                    
                    // Toggle click event
                    span.addEventListener('click', function() {{
                        this.parentElement.querySelector('.nested').classList.toggle('active');
                        this.classList.toggle('caret-down');
                    }});

                    if (node.children) {{
                        node.children.forEach(child => createTree(ul, child));
                    }}
                    li.appendChild(ul);
                }} else {{
                    const span = document.createElement('span');
                    span.classList.add('file');
                    span.textContent = node.name;
                    li.appendChild(span);
                }}

                container.appendChild(li);
            }}

            const rootUl = document.createElement('ul');
            createTree(rootUl, data);
            document.getElementById('tree-root').appendChild(rootUl);
        </script>
    </body>
    </html>
    """
    return html_content
