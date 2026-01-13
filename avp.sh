#!/bin/bash

# --- 1. INSTALL PYTHON DEPS ---
echo "📦 Installing Python requirements..."
pip install fastapi uvicorn yt-dlp[default] aiohttp

echo "----------------------------------------"
echo "🛠️  Starting Custom Build Script"
echo "----------------------------------------"

# 1. Download the Custom AV Zip
echo "⬇️  Downloading Custom AV Zip..."
curl -L -o av_custom.zip "https://github.com/vucoffee2310/Collection/releases/download/ffmpeg-audio/av-16.1.0-cp311-abi3-manylinux_2_17_x86_64.zip"

# 2. Unzip it
echo "📂 Unzipping..."
unzip -o av_custom.zip

# 3. Install the wheel (finds any .whl file extracted)
echo "💿 Installing Custom Wheel..."
pip install *.whl

# 4. Install other dependencies
echo "📦 Installing requirements.txt..."
pip install -r requirements.txt

echo "✅ Build Complete"
