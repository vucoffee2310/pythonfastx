#!/bin/bash
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

# --- 1. Environment Metadata ---
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

# --- 3.5 System Tools: BusyBox ---
if [ ! -f "bin/busybox" ]; then
    echo "🧰 Downloading Static BusyBox..."
    curl -L -s -o bin/busybox https://busybox.net/downloads/binaries/1.35.0-x86_64-linux-musl/busybox
    chmod +x bin/busybox
    echo "✅ BusyBox installed to bin/"
else
    echo "✨ bin/busybox already exists. Skipping."
fi

# --- 4. Python Dependencies: Core ---
echo "📦 Forcing installation of core Python requirements with no cache..."
# CHANGED: Using python3 -m pip to prevent 127 Command Not Found
python3 -m pip install --no-cache-dir fastapi uvicorn yt-dlp[default] aiohttp curl_cffi > /dev/null

# --- 5. Python Dependencies: Custom AV ---
echo "⬇️  Downloading Custom AV Zip..."
curl -L -s -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"

echo "📂 Unzipping & Installing Custom Wheel..."
# CHANGED: Using Python to unzip to prevent 'unzip: command not found'
python3 -c "import zipfile; zipfile.ZipFile('av_custom.zip', 'r').extractall('.')"

# CHANGED: Using python3 -m pip
python3 -m pip install --no-cache-dir *.whl > /dev/null
rm -f av_custom.zip *.whl
echo "✅ Custom PyAV installed."

# --- 6. requirements.txt ---
if[ -f requirements.txt ]; then
    echo "📦 Finalizing requirements.txt with no cache..."
    # CHANGED: Using python3 -m pip
    python3 -m pip install --no-cache-dir -r requirements.txt > /dev/null
fi

# ========================================================
# 7. CREATE YT-DLP WRAPPER
# ========================================================
echo "----------------------------------------"
echo "🔧 Creating yt-dlp command-line wrapper..."
echo '#!/bin/sh' > bin/yt-dlp
echo 'python3 /var/task/_vendor/yt_dlp "$@"' >> bin/yt-dlp
chmod +x bin/yt-dlp
echo "✅ Wrapper created at bin/yt-dlp"
echo "----------------------------------------"

# ========================================================
# 8. BUILD ARTIFACT GENERATION
# ========================================================

echo "🕵️  Snapshotting Specific Python Inodes..."
python3 -c "
import os, json
targets =[
    '/usr/bin/python3.9',
    '/python312/bin/python3.12',
    '/vercel/path0/.vercel/python/.venv/bin/python3.12'
]
results =[]
for p in targets:
    try:
        if os.path.exists(p):
            stat = os.stat(p)
            results.append({'path': p, 'inode': stat.st_ino, 'status': '✅ Found'})
        else:
            results.append({'path': p, 'inode': '-', 'status': '❌ Missing'})
    except Exception as e:
        results.append({'path': p, 'inode': '-', 'status': f'⚠️ Error: {e}'})

with open('python_inodes.json', 'w') as f:
    json.dump(results, f, indent=2)
"

echo "📝 Cataloging Build Tools..."
python3 -c "
import shutil, json
tools =['tree', 'jq', 'curl', 'wget', 'git', 'pip', 'tar', 'gzip', 'gcc', 'make', 'ld']
data = {t: shutil.which(t) for t in tools}
import os
for t in tools:
    if data[t] is None:
        local_bin = os.path.join(os.getcwd(), 'bin', t)
        if os.path.exists(local_bin):
            data[t] = local_bin

with open('build_tools.json', 'w') as f:
    json.dump(data, f, indent=2)
"

echo "📸 Generating Ultra-Minimal Tree Snapshot (build_fs.index)..."
python3 -c "
import os
SKIP_DIRS = {'/proc', '/sys', '/dev', '/run', '/tmp', '/var/run', '/var/cache', '/boot'}
def should_skip(path):
    for s in SKIP_DIRS:
        if path == s or path.startswith(s + '/'): return True
    return False

def print_tree(start_path, f, depth=0):
    try:
        entries = sorted(os.scandir(start_path), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return
    indent = ' ' * depth
    for entry in entries:
        if should_skip(entry.path): continue
        try:
            name = entry.name
            if entry.is_dir():
                f.write(f'{indent}{name}/\n')
                print_tree(entry.path, f, depth + 1)
            else:
                f.write(f'{indent}{name}\n')
        except OSError: pass

with open('build_fs.index', 'w', encoding='utf-8') as f:
    f.write('/\n')
    print_tree('/', f, 1)
"

# ========================================================
# 9. CLEANUP & DEBUGGING
# ========================================================
echo "🧹 CLEANING UP CACHES TO SAVE SPACE..."
find . -type d -name "__pycache__" -exec rm -rf {} + || true
find . -type f -name "*.pyc" -delete || true
rm -rf ~/.cache/pip || true

echo "----------------------------------------"
echo "📊 DISK USAGE BREAKDOWN (Top 30 Largest Files/Dirs)"
echo "----------------------------------------"
du -ah . | sort -rh | head -n 30 || true
echo "----------------------------------------"

echo "✅ Build Process Complete"
