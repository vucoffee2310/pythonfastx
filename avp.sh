#!/bin/bash

# 1. Setup paths
export INSTALL_DIR="$PWD/packages"
mkdir -p "$INSTALL_DIR"

# 2. Install standard requirements into our target folder
echo "📦 Installing FastAPI and build tools..."
pip install -r requirements.txt --target="$INSTALL_DIR"

# 3. Download Custom PyAV
URL="https://github.com/vucoffee2310/youtubedownloader/releases/download/pyav-custom/pyav-custom.tar.gz"
FILENAME="pyav-custom.tar.gz"
DIRNAME="pyav"

echo "⬇️ Downloading PyAV source..."
curl -L -o "$FILENAME" "$URL"
tar -xf "$FILENAME"

# 4. Build and Install PyAV to our target folder
if [ -d "$DIRNAME" ]; then
    cd "$DIRNAME" || exit 1
    echo "⚙️ Configuring Build Paths..."
    export PKG_CONFIG_PATH="$(pwd)/lib/pkgconfig:$PKG_CONFIG_PATH"
    export LD_LIBRARY_PATH="$(pwd)/lib:$LD_LIBRARY_PATH"
    
    # Install PyAV specifically into the packages folder
    echo "🔨 Building PyAV..."
    pip install . --target="$INSTALL_DIR"
    
    # CRITICAL: Copy FFmpeg shared libraries (.so) so they are bundled
    echo "📂 Bundling shared libraries..."
    cp -r lib/*.so* "$INSTALL_DIR/"
    cd ..
else
    echo "❌ Error: PyAV folder not found."
    exit 1
fi

echo "✅ Build Complete. Files are in /packages"
