set -e

# ========================================================
# 🛑 STOP CHECK: PREVENT DOUBLE EXECUTION
# ========================================================
# Vercel runs this script twice. 
# Run #1: Global Install (We want this).
# Run #2: Python Builder (We want to skip this).
MARKER_FILE="build_complete.marker"

if [ -f "$MARKER_FILE" ]; then
    echo "----------------------------------------"
    echo "⏩ Skipping re-initialization (Marker found)."
    echo "   Everything is already installed."
    echo "----------------------------------------"
    exit 0
fi

echo "----------------------------------------"
echo "🛠️  Starting Custom Build Script (Run #1)"
echo "----------------------------------------"

# --- 1. Environment Metadata ---
echo "🔍 Capturing Build Environment Metadata..."
{
  echo "=== BUILD DATE ==="
  date
  echo -e "\n=== BUILD OS INFO (/etc/os-release) ==="
  cat /etc/os-release || echo "N/A"
  echo -e "\n=== BUILD KERNEL (uname) ==="
  uname -a
  echo -e "\n=== BUILD GLIBC / LDD VERSION ==="
  ldd --version || echo "ldd not found"
} | tee build_env_info.txt

mkdir -p bin

# --- 2. System Tools (Tree) ---
if [ ! -f "bin/tree" ]; then
    if command -v yum &> /dev/null; then
        echo "🌲 Installing Tree via yum..."
        # Silence output to keep logs clean
        yum install -y tree > /dev/null 2>&1 || true
        if command -v tree &> /dev/null; then
            cp $(which tree) bin/
        fi
    else
        echo "⚠️  Yum not found, skipping tree system install."
    fi
else
    echo "✨ Tree already installed."
fi

# --- 3. JQ ---
if [ ! -f "bin/jq" ]; then
    echo "🦆 Downloading Static JQ..."
    curl -L -s -o bin/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64
    chmod +x bin/jq
else
    echo "✨ JQ already installed."
fi

# --- 4. Deno ---
if [ ! -f "bin/deno" ]; then
    echo "🦕 Installing Deno..."
    export DENO_INSTALL="$PWD/deno_temp"
    curl -fsSL https://deno.land/install.sh | sh
    
    echo "🚚 Moving Deno binary to ./bin/..."
    if [ -f "$PWD/deno_temp/bin/deno" ]; then
        cp "$PWD/deno_temp/bin/deno" bin/
        chmod +x bin/deno
        rm -rf "$PWD/deno_temp"
        echo "✅ Deno installed successfully."
    else
        echo "❌ Error: Deno binary not found after install."
        exit 1
    fi
else
    echo "✨ Deno already installed."
fi

# --- 5. Python Dependencies ---
# We run this explicitly in Run #1 so binaries are available immediately
echo "📦 Installing Python requirements..."
pip install fastapi uvicorn yt-dlp[default] aiohttp > /dev/null

# --- 6. Custom AV (Heavy Download) ---
# We rely on python import check to avoid re-downloading if something goes wrong with marker
if python3 -c "import av" &> /dev/null; then
    echo "✨ Custom PyAV already installed & working."
else
    echo "⬇️  Downloading Custom AV Zip..."
    curl -L -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"
    
    echo "📂 Unzipping..."
    unzip -q -o av_custom.zip
    
    echo "💿 Installing Custom Wheel..."
    pip install *.whl > /dev/null
    
    echo "🧹 Removing extracted files and archives..."
    rm -f av_custom.zip
    rm -f *.whl
fi

if [ -f requirements.txt ]; then
    echo "📦 Installing requirements.txt..."
    pip install -r requirements.txt > /dev/null
fi

echo "----------------------------------------"
echo "✅ Build Process Finished"
echo "Directory structure (bin folder check):"
./bin/tree -L 2 bin/

# --- 7. Create Marker File ---
# This ensures Run #2 sees this file and exits immediately
touch "$MARKER_FILE"
