import os
import sys
import subprocess
import platform
import shutil
import json
from typing import Dict, List

# ========================================================
# PATH CONFIGURATION
# ========================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = "/var/task" if os.path.exists("/var/task") else os.getcwd()

paths = {
    "root": project_root,
    "vendor": os.path.join(project_root, "_vendor"),
    "lib": os.path.join(project_root, "lib"),
    "bin": os.path.join(project_root, "bin"),
    "build_info": os.path.join(project_root, "build_env_info.txt"),
    "build_tools": os.path.join(project_root, "build_tools.json"),
    "build_inodes": os.path.join(project_root, "python_inodes.json"),
    "build_index": os.path.join(project_root, "build_fs.index")
}

BUILD_FS_CACHE: Dict[str, List[dict]] = {}

def setup_environment():
    """Configures system paths and permissions for binaries/libs."""
    # Link Vendor Libraries
    if os.path.exists(paths["vendor"]):
        if paths["vendor"] not in sys.path:
            sys.path.insert(0, paths["vendor"])
        os.environ["PYTHONPATH"] = f"{paths['vendor']}:{os.environ.get('PYTHONPATH', '')}"

    # Link Executables
    if os.path.exists(paths["bin"]):
        os.environ["PATH"] = f"{paths['bin']}:{os.environ.get('PATH', '')}"
        subprocess.run(f"chmod -R +x {paths['bin']}", shell=True, stderr=subprocess.DEVNULL)

    if os.path.exists(paths["lib"]):
        os.environ["LD_LIBRARY_PATH"] = f"{paths['lib']}:{os.environ.get('LD_LIBRARY_PATH', '')}"

def get_human_size(size_bytes):
    if isinstance(size_bytes, str): return size_bytes
    for unit in ['B','KB','MB','GB']:
        if size_bytes < 1024: return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"

def load_build_fs_cache():
    if not os.path.exists(paths["build_index"]): return
    try:
        dir_stack = [] 
        with open(paths["build_index"], 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.lstrip(' ')
                if not stripped: continue
                content = stripped.rstrip('\n')
                depth = len(line) - len(stripped)
                is_dir = content.endswith('/')
                name = content.rstrip('/')
                
                if depth == 0:
                    current_path = "/" if name == "" else name
                    dir_stack = [current_path]
                    if current_path not in BUILD_FS_CACHE:
                        BUILD_FS_CACHE[current_path] = []
                    continue

                while len(dir_stack) > depth: dir_stack.pop()
                parent_path = dir_stack[-1]
                if parent_path == "/": abs_path = f"/{name}"
                else: abs_path = f"{parent_path}/{name}"
                
                if parent_path not in BUILD_FS_CACHE: BUILD_FS_CACHE[parent_path] = []
                
                BUILD_FS_CACHE[parent_path].append({
                    "name": name, "path": abs_path, "is_dir": is_dir, "size": "-",
                    "ext": os.path.splitext(name)[1].lower() if not is_dir else ""
                })
                
                if is_dir:
                    dir_stack.append(abs_path)
                    if abs_path not in BUILD_FS_CACHE: BUILD_FS_CACHE[abs_path] = []
    except Exception as e: print(f"Error loading tree index: {e}")

def get_size_str(path):
    total = 0
    try:
        if os.path.isfile(path): total = os.path.getsize(path)
        else:
            res = subprocess.run(["du", "-sb", path], stdout=subprocess.PIPE, text=True)
            total = int(res.stdout.split()[0])
    except: pass
    return get_human_size(total)

def get_runtime_env_info():
    info = { "python": sys.version.split()[0], "platform": platform.platform(), "glibc": platform.libc_ver()[1] }
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f: info["os"] = f.read().splitlines()[0].replace('"', '')
        else: info["os"] = "Unknown OS"
    except: info["os"] = "Error reading OS"
    return info

def compare_tools():
    build_data = {}
    if os.path.exists(paths["build_tools"]):
        try:
            with open(paths["build_tools"], 'r') as f: build_data = json.load(f)
        except: pass
    tool_list = list(build_data.keys()) if build_data else ['tree', 'jq', 'curl', 'git', 'python3']
    comparison = []
    for tool in tool_list:
        build_path = build_data.get(tool)
        runtime_path = shutil.which(tool)
        status = "Unknown"
        if build_path and runtime_path: status = "✅ Same Path" if build_path == runtime_path else "⚠️ Path Changed"
        elif build_path and not runtime_path: status = "❌ Missing in Runtime"
        elif not build_path and runtime_path: status = "✨ New in Runtime"
        else: status = "⛔ Not Available"
        comparison.append({ "name": tool, "build": build_path or "-", "runtime": runtime_path or "-", "status": status })
    return comparison

def get_python_inodes():
    if os.path.exists(paths["build_inodes"]):
        try:
            with open(paths["build_inodes"], 'r') as f: return json.load(f)
        except: pass
    return []

# Initialize cache on module load
load_build_fs_cache()