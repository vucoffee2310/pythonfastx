set -e

# ========================================================
# 🧬 PYTHON IDENTITY TEST
# ========================================================
echo "----------------------------------------"
echo "🕵️  PYTHON IDENTITY REPORT"
echo "----------------------------------------"
PY_PATH=$(which python3)
INODE=$(ls -i "$PY_PATH" | awk '{print $1}')
echo "📍 Executable Path: $PY_PATH"
echo "🆔 Physical ID (Inode): $INODE"
echo "🔗 Shortcut Check: $(ls -l "$PY_PATH")"
echo "🏠 Real Home: $(python3 -c 'import os; print(os.path.realpath(os.sys.executable))')"
echo "----------------------------------------"

# --- 1. Environment Metadata (Run once) ---
if [ ! -f "build_env_info.txt" ]; then
    echo "🔍 Capturing Build Environment Metadata..."
    {
      echo "=== BUILD DATE ==="
      date
      echo -e "\n=== BUILD OS INFO (/etc/os-release) ==="
      cat /etc/os-release || echo "N/A"
      echo -e "\n=== BUILD GLIBC VERSION ==="
      ldd --version || echo "ldd not found"
    } | tee build_env_info.txt
fi

mkdir -p bin

# --- 2. System Tools: Tree ---
if [ ! -f "bin/tree" ]; then
    if command -v yum &> /dev/null; then
        echo "🌲 Installing Tree via yum..."
        yum install -y tree > /dev/null 2>&1 || true
        if command -v tree &> /dev/null; then
            cp $(which tree) bin/
            echo "✅ Tree copied to bin/"
        fi
    fi
else
    echo "✨ bin/tree already exists. Skipping."
fi

# --- 3. System Tools: JQ ---
if [ ! -f "bin/jq" ]; then
    echo "🦆 Downloading Static JQ..."
    curl -L -s -o bin/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64
    chmod +x bin/jq
    echo "✅ JQ installed to bin/"
else
    echo "✨ bin/jq already exists. Skipping."
fi

# --- 4. System Tools: Deno ---
if [ ! -f "bin/deno" ]; then
    echo "🦕 Installing Deno..."
    export DENO_INSTALL="$PWD/deno_temp"
    curl -fsSL -s https://deno.land/install.sh | sh > /dev/null
    
    if [ -f "$PWD/deno_temp/bin/deno" ]; then
        cp "$PWD/deno_temp/bin/deno" bin/
        chmod +x bin/deno
        rm -rf "$PWD/deno_temp"
        echo "✅ Deno installed to bin/"
    fi
else
    echo "✨ bin/deno already exists. Skipping."
fi

# --- 5. Python Dependencies: Core ---
if ! python3 -c "import fastapi" &> /dev/null; then
    echo "📦 Installing core Python requirements..."
    pip install fastapi uvicorn yt-dlp[default] aiohttp > /dev/null
else
    echo "✨ Python core libraries already present. Skipping."
fi

# --- 6. Python Dependencies: Custom AV ---
if ! python3 -c "import av" &> /dev/null; then
    echo "⬇️  Downloading Custom AV Zip..."
    curl -L -s -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"
    echo "📂 Unzipping & Installing Custom Wheel..."
    unzip -q -o av_custom.zip
    pip install *.whl > /dev/null
    rm -f av_custom.zip *.whl
    echo "✅ Custom PyAV installed."
else
    echo "✨ Custom PyAV already present. Skipping."
fi

# --- 7. requirements.txt ---
if [ -f requirements.txt ]; then
    echo "📦 Finalizing requirements.txt..."
    pip install -r requirements.txt > /dev/null
fi

echo "----------------------------------------"
echo "📊 Final Workspace Check"
./bin/tree -L 2 bin/

# --- 8. TOOL CATALOGUE ---
echo "📝 Cataloging Build Tools..."
python3 -c "
import shutil, json
tools = ['tree', 'jq', 'deno', 'curl', 'wget', 'git', 'python3', 'pip', 'tar', 'gzip', 'ffmpeg', 'gcc', 'make']
data = {t: shutil.which(t) for t in tools}
with open('build_tools.json', 'w') as f:
    json.dump(data, f, indent=2)
"

# --- 9. FILESYSTEM SNAPSHOT (For User Browsing) ---
echo "📸 Snapshotting Build File System Structure..."
python3 -c "
import os

# We generate a flat index file: TYPE|SIZE|PATH
# This allows the runtime API to reconstruct the tree without creating a massive JSON file.
index_file = 'build_fs.index'

with open(index_file, 'w', encoding='utf-8') as f:
    # 1. Full snapshot of Workspace (Current Dir)
    cwd = os.getcwd()
    # Add root of cwd specifically
    f.write(f'D|0|{cwd}\n')
    
    for root, dirs, files in os.walk(cwd):
        for name in dirs + files:
            path = os.path.join(root, name)
            is_dir = os.path.isdir(path)
            try: size = os.path.getsize(path) if not is_dir else 0
            except: size = 0
            type_char = 'D' if is_dir else 'F'
            f.write(f'{type_char}|{size}|{path}\n')

    # 2. Shallow snapshot of System Roots (to avoid timeout/size issues)
    # We want to see /usr/bin, /lib, etc. but not scan all of /
    target_roots = ['/bin', '/lib', '/lib64', '/usr', '/opt', '/etc']
    
    # Add the roots themselves
    f.write('D|0|/\n')
    for tr in target_roots:
        if os.path.exists(tr):
            f.write(f'D|0|{tr}\n')

    for sys_root in target_roots:
        if not os.path.exists(sys_root): continue
        # Walk with depth limit
        for root, dirs, files in os.walk(sys_root):
            # Calculate depth relative to this root
            rel_depth = root[len(sys_root):].count(os.sep)
            
            # Limit depth to 3 levels inside system folders to keep file size small
            if rel_depth > 3:
                dirs[:] = [] # Stop recursing
                continue
            
            for name in dirs + files:
                path = os.path.join(root, name)
                is_dir = os.path.isdir(path)
                try: size = os.path.getsize(path) if not is_dir else 0
                except: size = 0
                type_char = 'D' if is_dir else 'F'
                f.write(f'{type_char}|{size}|{path}\n')

print(f'✅ Snapshot saved to {index_file}')
"

echo "✅ Build Process Complete"
