#!/bin/bash
set -e

echo "----------------------------------------"
echo "🛠️  Starting Custom Build Script"
echo "----------------------------------------"

# ========================================================
# 0. CAPTURE BUILD ENVIRONMENT INFO
# ========================================================
# We save this to a file so the Python app can read it 
# at runtime to show you what the build server looked like.
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
# We must create a local 'bin' directory. Vercel will include this 
# in the deployment, unlike files installed to /usr/bin.
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
# We download the static binary because the 'yum' version often depends 
# on libraries (libonig) that won't exist in the runtime.
echo "🦆 Downloading Static JQ..."
curl -L -o bin/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64
chmod +x bin/jq

echo "✅ System tools copied to ./bin/"

# 4. INSTALL PYTHON DEPS
echo "📦 Installing Python requirements..."
pip install fastapi uvicorn yt-dlp[default] aiohttp

# 5. DOWNLOAD CUSTOM AV
echo "⬇️  Downloading Custom AV Zip..."
curl -L -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"

# 6. UNZIP
echo "📂 Unzipping..."
unzip -o av_custom.zip

# 7. INSTALL WHEEL
echo "💿 Installing Custom Wheel..."
pip install *.whl

# 8. CLEANUP ARCHIVES AND WHEELS
echo "🧹 Removing extracted files and archives..."
rm -f av_custom.zip
rm -f *.whl

# 9. INSTALL PROJECT REQUIREMENTS
if [ -f requirements.txt ]; then
    echo "📦 Installing requirements.txt..."
    pip install -r requirements.txt
fi

echo "----------------------------------------"
echo "📊 Final Verification"
echo "Directory structure (bin folder check):"
# We use the local tree command we just installed to verify it works immediately
./bin/tree -L 2

echo "✅ Build Complete & Workspace Cleaned"
