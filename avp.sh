set -e

# ========================================================
# 1. SETUP & METADATA
# ========================================================
echo "----------------------------------------"
echo "🕵️  PYTHON IDENTITY REPORT"
echo "----------------------------------------"
PY_PATH=$(which python3)
echo "📍 Executable: $PY_PATH"
echo "🏠 Real Home: $(python3 -c 'import os; print(os.path.realpath(os.sys.executable))')"

# Build Metadata
if [ ! -f "build_env_info.txt" ]; then
    echo "🔍 Capturing Build Environment Metadata..."
    {
      echo "=== BUILD DATE ==="; date
      echo -e "\n=== OS INFO ==="; cat /etc/os-release || echo "N/A"
      echo -e "\n=== GLIBC ==="; ldd --version || echo "N/A"
    } | tee build_env_info.txt
fi

mkdir -p bin

# ========================================================
# 2. INSTALLATION OF TOOLS
# ========================================================

# Tree
if [ ! -f "bin/tree" ]; then
    if command -v yum &> /dev/null; then
        echo "🌲 Installing Tree..."
        yum install -y tree > /dev/null 2>&1 || true
        [ -f "$(which tree)" ] && cp $(which tree) bin/
    fi
else echo "✨ tree exists"; fi

# JQ
if [ ! -f "bin/jq" ]; then
    echo "🦆 Downloading JQ..."
    curl -L -s -o bin/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64
    chmod +x bin/jq
else echo "✨ jq exists"; fi

# Deno
if [ ! -f "bin/deno" ]; then
    echo "🦕 Installing Deno..."
    export DENO_INSTALL="$PWD/deno_temp"
    curl -fsSL -s https://deno.land/install.sh | sh > /dev/null
    [ -f "$PWD/deno_temp/bin/deno" ] && cp "$PWD/deno_temp/bin/deno" bin/ && chmod +x bin/deno
    rm -rf "$PWD/deno_temp"
else echo "✨ deno exists"; fi

# Python Core
if ! python3 -c "import fastapi" &> /dev/null; then
    echo "📦 Installing core libs..."
    pip install fastapi uvicorn yt-dlp[default] aiohttp > /dev/null
fi

# Custom AV
if ! python3 -c "import av" &> /dev/null; then
    echo "⬇️  Downloading PyAV..."
    curl -L -s -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"
    unzip -q -o av_custom.zip
    pip install *.whl > /dev/null
    rm -f av_custom.zip *.whl
fi

if [ -f requirements.txt ]; then
    echo "📦 Requirements.txt found..."
    pip install -r requirements.txt > /dev/null
fi

# ========================================================
# 3. TOOL AUDIT (SNAPSHOT BUILD STATE)
# ========================================================
echo "📸 Snapshotting Build-Phase Tools..."
python3 -c '
import os
import json
import stat

def get_executables():
    tools = set()
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for p in paths:
        if not os.path.exists(p): continue
        try:
            for f in os.listdir(p):
                full_path = os.path.join(p, f)
                # Check if executable
                if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                    tools.add(f)
        except Exception:
            pass
    return sorted(list(tools))

tools = get_executables()
data = {
    "count": len(tools),
    "tools": tools,
    "path_env": os.environ.get("PATH")
}

with open("build_phase_tools.json", "w") as f:
    json.dump(data, f, indent=2)

print(f"✅ Indexed {len(tools)} executables to build_phase_tools.json")
'

echo "----------------------------------------"
echo "📊 Build Complete"
./bin/tree -L 2 bin/
