#!/bin/bash
set -e  # Exit on error

# --- 1. INSTALL SYSTEM TOOLS ---
echo "🛠️  Installing system utilities..."
# Using yum (standard for Amazon Linux / Lambda Build Images)
sudo yum update -y
sudo yum install -y tree jq busybox

echo "----------------------------------------"
echo "🛠️  Starting Custom Build Script"
echo "----------------------------------------"

# --- 2. INSTALL PYTHON DEPS ---
echo "📦 Installing Python requirements..."
pip install fastapi uvicorn yt-dlp[default] aiohttp

# --- 3. DOWNLOAD & INSTALL CUSTOM AV ---
echo "⬇️  Downloading Custom AV Zip..."
curl -L -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"

echo "📂 Unzipping..."
unzip -o av_custom.zip

echo "💿 Installing Custom Wheel..."
pip install *.whl

# --- 4. CLEANUP (CRITICAL FOR LAMBDA SIZE) ---
echo "🧹 Removing extracted archives and wheels to save space..."
rm -f av_custom.zip
rm -f *.whl
# Optional: Remove any leftover __pycache__ folders
find . -type d -name "__pycache__" -exec rm -rf {} +

# --- 5. FINAL INSTALL ---
echo "📦 Installing requirements.txt..."
pip install -r requirements.txt

echo "----------------------------------------"
echo "📊 Verifying Build Area"
ls -la  # Running the command you requested to see the final state
tree -L 1 # Show directory structure briefly
echo "----------------------------------------"

echo "✅ Build Complete & Workspace Cleaned"
