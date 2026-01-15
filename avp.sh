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

# ========================================================
# 8. BUILD ARTIFACT GENERATION (Snapshots)
# ========================================================

echo "📝 Cataloging Build Tools..."
python3 -c "
import shutil, json
tools = ['tree', 'jq', 'deno', 'curl', 'wget', 'git', 'python3', 'pip', 'tar', 'gzip', 'ffmpeg', 'gcc', 'make', 'ld']
data = {t: shutil.which(t) for t in tools}
with open('build_tools.json', 'w') as f:
    json.dump(data, f, indent=2)
"

echo "📸 Snapshotting Build File System Structure..."
python3 -c "
import os

# Output Format: TYPE|SIZE|PATH
# D = Directory, F = File
index_file = 'build_fs.index'

def scan_dir(start_path, max_depth=None, current_depth=0):
    entries = []
    try:
        with os.scandir(start_path) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                    size = entry.stat().st_size if not is_dir else 0
                    entries.append(( 'D' if is_dir else 'F', size, entry.path ))
                    
                    if is_dir:
                        # Recurse if no limit or within limit
                        if max_depth is None or current_depth < max_depth:
                            entries.extend(scan_dir(entry.path, max_depth, current_depth + 1))
                except:
                    pass
    except:
        pass
    return entries

with open(index_file, 'w', encoding='utf-8') as f:
    cwd = os.getcwd()
    
    # 1. Full Snapshot of Workspace (Current Directory)
    # We add the root entry first
    f.write(f'D|0|{cwd}\n')
    for item in scan_dir(cwd):
        f.write(f'{item[0]}|{item[1]}|{item[2]}\n')

    # 2. Shallow Snapshot of System Roots
    # We want to see what's in /bin, /usr/bin, /lib without timing out scanning the whole drive
    sys_roots = ['/', '/bin', '/usr', '/lib', '/lib64', '/opt', '/etc']
    
    for root in sys_roots:
        if os.path.exists(root):
            # Write the root itself
            f.write(f'D|0|{root}\n')
            # Scan with depth limit of 2 (enough to see /usr/bin/python but not deep libs)
            for item in scan_dir(root, max_depth=2):
                f.write(f'{item[0]}|{item[1]}|{item[2]}\n')

print(f'✅ Snapshot saved to {index_file}')
"

echo "✅ Build Process Complete"
