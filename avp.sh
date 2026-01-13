#!/bin/bash
set -e

echo "🛠️  Installing system utilities..."

# Detect package manager and install tools without sudo
if command -v yum &> /dev/null; then
    yum update -y
    yum install -y tree jq busybox
elif command -v apt-get &> /dev/null; then
    apt-get update
    apt-get install -y tree jq
else
    echo "⚠️  Could not find yum or apt-get. Skipping system tool installation."
fi

echo "----------------------------------------"
echo "🛠️  Starting Custom Build Script"
echo "----------------------------------------"

# 1. INSTALL PYTHON DEPS
echo "📦 Installing Python requirements..."
pip install fastapi uvicorn yt-dlp[default] aiohttp

# 2. DOWNLOAD CUSTOM AV
echo "⬇️  Downloading Custom AV Zip..."
curl -L -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"

# 3. UNZIP
echo "📂 Unzipping..."
unzip -o av_custom.zip

# 4. INSTALL WHEEL
echo "💿 Installing Custom Wheel..."
pip install *.whl

# 5. CLEANUP ARCHIVES AND WHEELS (Crucial for Lambda size)
echo "🧹 Removing extracted files and archives..."
rm -f av_custom.zip
rm -f *.whl

# 6. INSTALL PROJECT REQUIREMENTS
if [ -f requirements.txt ]; then
    echo "📦 Installing requirements.txt..."
    pip install -r requirements.txt
fi

echo "----------------------------------------"
echo "📊 Final Verification"
echo "Current directory contents:"
ls -la

echo "Directory structure:"
tree -L 1

echo "✅ Build Complete & Workspace Cleaned"
