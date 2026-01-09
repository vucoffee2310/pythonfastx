#!/bin/bash
set -e # Stop on error

# 1. Configuration
INSTALL_DIR="$PWD/packages"
mkdir -p "$INSTALL_DIR"
URL="https://github.com/vucoffee2310/youtubedownloader/releases/download/pyav-custom/pyav-custom.tar.gz"
FILENAME="pyav-custom.tar.gz"
EXTRACT_DIR="pyav"

# 2. Install Standard Requirements first (FastAPI, etc.)
echo "📦 Installing requirements.txt..."
pip install -r requirements.txt --target="$INSTALL_DIR"

# 3. Download and Extract PyAV Source
echo "⬇️ Downloading PyAV..."
curl -L -o "$FILENAME" "$URL"
# Remove old folder if exists
rm -rf "$EXTRACT_DIR"
tar -xf "$FILENAME"

# 4. Build and Install
if [ -d "$EXTRACT_DIR" ]; then
    cd "$EXTRACT_DIR" || exit 1
    
    # The setup.py expects to find 'lib' and 'include' here.
    # We get the absolute path for the flag.
    FFMPEG_ROOT="$(pwd)"
    
    echo "⚙️ Found FFmpeg root at: $FFMPEG_ROOT"
    
    # CRITICAL STEP 1: Copy .so files to the deployment folder
    # We do this BEFORE build so they are ready
    echo "📂 Copying shared libraries to $INSTALL_DIR..."
    if [ -d "lib" ]; then
        cp -v lib/*.so* "$INSTALL_DIR/"
    else
        echo "⚠️ Warning: 'lib' folder not found in extracted tarball. Build might fail."
    fi

    # CRITICAL STEP 2: Run the installation
    # We use --global-option to pass the flag to setup.py
    echo "🔨 Compiling PyAV..."
    
    # We set PKG_CONFIG_PATH just in case, though your setup.py prefers the flag
    export PKG_CONFIG_PATH="$FFMPEG_ROOT/lib/pkgconfig"
    
    # This command passes "--ffmpeg-dir" to your python script
    pip install . \
        --target="$INSTALL_DIR" \
        --no-deps \
        --global-option="build_ext" \
        --global-option="--ffmpeg-dir=$FFMPEG_ROOT"

    cd ..
    
    # Cleanup to save space (Vercel has a 250MB size limit)
    rm -rf "$EXTRACT_DIR" "$FILENAME"
    echo "✅ Build Success."
else
    echo "❌ Error: Directory $EXTRACT_DIR not created."
    exit 1
fi
