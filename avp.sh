#!/bin/bash
set -e

echo "🚀 Starting custom Vercel build script..."
mkdir -p bin

# --- 1. System Tools ---
if [ ! -f "bin/jq" ]; then
    echo "🦆 Downloading Static JQ..."
    curl -L -s -o bin/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64
    chmod +x bin/jq
fi

if [ ! -f "bin/busybox" ]; then
    echo "🧰 Downloading Static BusyBox..."
    curl -L -s -o bin/busybox https://busybox.net/downloads/binaries/1.35.0-x86_64-linux-musl/busybox
    chmod +x bin/busybox
fi

# --- 2. Python Dependencies ---
echo "📦 Installing core Python packages..."
python3 -m pip install --no-cache-dir fastapi uvicorn yt-dlp[default] aiohttp curl_cffi > /dev/null

echo "⬇️ Downloading Custom AV Zip..."
curl -L -s -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"

echo "📂 Extracting Custom Wheel..."
python3 -c "import zipfile; zipfile.ZipFile('av_custom.zip', 'r').extractall('.')"

echo "⚙️ Installing Custom Wheel..."
python3 -m pip install --no-cache-dir *.whl > /dev/null
rm -f av_custom.zip *.whl

# (FIXED: Added missing space after 'if [')
if [ -f requirements.txt ]; then
    echo "📦 Finalizing requirements.txt..."
    python3 -m pip install --no-cache-dir -r requirements.txt > /dev/null
fi

# --- 3. CREATE YT-DLP WRAPPER ---
echo "🔧 Creating yt-dlp command-line wrapper..."
echo '#!/bin/sh' > bin/yt-dlp
echo 'python3 /var/task/_vendor/yt_dlp "$@"' >> bin/yt-dlp
chmod +x bin/yt-dlp

# --- 4. ARTIFACT GENERATION ---
echo "📝 Cataloging Build Tools..."
python3 -c "
import shutil, json, os
tools =['tree', 'jq', 'curl', 'wget', 'git', 'pip', 'tar', 'gzip', 'gcc', 'make', 'ld']
data = {t: shutil.which(t) for t in tools}
for t in tools:
    if data[t] is None:
        local_bin = os.path.join(os.getcwd(), 'bin', t)
        if os.path.exists(local_bin):
            data[t] = local_bin
with open('build_tools.json', 'w') as f:
    json.dump(data, f, indent=2)
"

echo "📸 Generating Minimal Tree Snapshot..."
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

# --- 5. CLEANUP TO AVOID 250MB LIMIT ---
echo "🧹 CLEANING UP CACHES TO SAVE SPACE..."
find . -type d -name "__pycache__" -exec rm -rf {} + || true
find . -type f -name "*.pyc" -delete || true
rm -rf ~/.cache/pip || true

echo "----------------------------------------"
echo "📊 DISK USAGE BREAKDOWN (Top 30 Largest Files)"
echo "----------------------------------------"
du -ah . | sort -rh | head -n 30 || true

echo "✅ Build Process Complete!"
