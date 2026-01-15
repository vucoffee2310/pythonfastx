#!/bin/bash
set -e

echo "----------------------------------------"
echo "🛠️  Starting Custom Build Script"
echo "----------------------------------------"

# ========================================================
# 0. CAPTURE BUILD ENVIRONMENT INFO
# ========================================================
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

# ========================================================
# 1. PREPARE LOCAL BIN FOLDER
# ========================================================
mkdir -p bin

# 2. INSTALL TREE (Install via yum, then grab the binary)
if command -v yum &> /dev/null; then
    echo "🌲 Installing Tree via yum..."
    yum install -y tree
    # CRITICAL: Copy the binary from system path to project path
    cp $(which tree) bin/
else
    echo "⚠️  Yum not found, skipping tree system install."
fi

# 3. INSTALL JQ (Download Static Binary)
echo "🦆 Downloading Static JQ..."
curl -L -o bin/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64
chmod +x bin/jq

# 4. INSTALL DENO (Required for yt-dlp PO Token)
echo "🦕 Installing Deno..."
# We set a temporary install path to ensure we know exactly where it lands
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

echo "✅ System tools (tree, jq, deno) copied to ./bin/"

# 5. INSTALL PYTHON DEPS
echo "📦 Installing Python requirements..."
pip install fastapi uvicorn yt-dlp[default] aiohttp

# 6. DOWNLOAD CUSTOM AV
echo "⬇️  Downloading Custom AV Zip..."
curl -L -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"

# 7. UNZIP
echo "📂 Unzipping..."
unzip -o av_custom.zip

# 8. INSTALL WHEEL
echo "💿 Installing Custom Wheel..."
pip install *.whl

# 9. CLEANUP ARCHIVES AND WHEELS
echo "🧹 Removing extracted files and archives..."
rm -f av_custom.zip
rm -f *.whl

# 10. INSTALL PROJECT REQUIREMENTS
if [ -f requirements.txt ]; then
    echo "📦 Installing requirements.txt..."
    pip install -r requirements.txt
fi

echo "----------------------------------------"
echo "📊 Final Verification"
echo "Directory structure (bin folder check):"
./bin/tree -L 2

echo "✅ Build Complete & Workspace Cleaned"
