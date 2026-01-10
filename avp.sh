#!/bin/bash

# --- 1. INSTALL PYTHON DEPS ---
echo "📦 Installing Python requirements..."
pip install fastapi uvicorn cython wheel setuptools av

# # --- 2. SETUP FOLDERS ---
# APP_ROOT=$(pwd)
# BUILD_DIR="pyav_build"
# LIB_DIR="lib"
# BIN_DIR="bin"  # <--- NEW: Folder for executables

# mkdir -p $BUILD_DIR
# mkdir -p $LIB_DIR
# mkdir -p $BIN_DIR

# # --- 3. INSTALL CUSTOM TOOLS (Tree, JQ, Busybox) ---
# echo "🛠 Installing System Tools..."

# # A. TREE: Install via yum, then copy the binary to our local bin folder
# # Vercel build images allow yum, but the files disappear unless we copy them to $APP_ROOT
# yum install -y tree
# cp $(which tree) $BIN_DIR/

# # B. JQ: Download static binary (Great for parsing JSON in shell)
# curl -L -o $BIN_DIR/jq https://github.com/stedolan/jq/releases/download/jq-1.6/jq-linux64

# # C. BUSYBOX: The "Swiss Army Knife" (provides wget, vi, grep, tar, etc if missing)
# curl -L -o $BIN_DIR/busybox https://busybox.net/downloads/binaries/1.31.0-defconfig-multiarch-musl/busybox-x86_64

# # D. FFMPEG (Static): Optional, but useful for shell usage (not just python lib)
# # Uncomment the next line if you want the 'ffmpeg' command in the shell too
# # curl -L -o $BIN_DIR/ffmpeg https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar -xJ -C $BIN_DIR --strip-components=1 --wildcards '*/ffmpeg'

# # Make everything executable
# chmod +x $BIN_DIR/*

# # --- 4. PYAV BUILD (Same as before) ---
# URL="https://github.com/vucoffee2310/youtubedownloader/releases/download/pyav-custom/pyav-custom.tar.gz"
# FILENAME="pyav-custom.tar.gz"

# if [ ! -f "$FILENAME" ]; then
#     echo "⬇️ Downloading PyAV source..."
#     curl -L -o "$FILENAME" "$URL"
# fi

# echo "📦 Extracting PyAV..."
# tar -xf "$FILENAME" -C $BUILD_DIR --strip-components=1

# cd $BUILD_DIR
# export PKG_CONFIG_PATH="$(pwd)/lib/pkgconfig"
# export CFLAGS="-I$(pwd)/include"
# export LDFLAGS="-L$(pwd)/lib -Wl,-rpath,'\$ORIGIN/../../lib'"

# echo "🔨 Building PyAV..."
# pip install . -v

# # --- 5. CLEANUP & BUNDLE ---
# cd "$APP_ROOT"
# echo "📋 Bundling libraries..."
# cp -r $BUILD_DIR/lib/*.so* $LIB_DIR/

# rm -rf $BUILD_DIR $FILENAME
# echo "✅ Build & Tools Installation Complete."

# # --- 6. SNAPSHOT BUILD FILESYSTEM (NEW) ---
# echo "📸 Creating Build Phase Snapshot..."
# SNAPSHOT_FILE="build_snapshot.log"

# {
#     echo "========================================"
#     echo "BUILD PHASE SNAPSHOT"
#     echo "Timestamp: $(date)"
#     echo "User: $(whoami)"
#     echo "Working Directory (CWD): $(pwd)"
#     echo "========================================"
#     echo ""
#     echo "--- [1] CONTENTS OF ROOT (/) ---"
#     ls -la /
#     echo ""
#     echo "--- [2] CONTENTS OF /vercel ---"
#     # Vercel usually mounts things here
#     ls -R /vercel 2>/dev/null || echo "/vercel not found"
#     echo ""
#     echo "--- [3] CONTENTS OF WORK DIR (Your App) ---"
#     # Use the tree binary we just put in bin/
#     ./bin/tree -L 4
#     echo ""
#     echo "--- [4] ENVIRONMENT VARIABLES (Safe Subset) ---"
#     printenv | grep -E "PATH|LANG|VERCEL|PWD|HOME"
# } > "$SNAPSHOT_FILE"

# echo "✅ Snapshot saved to $SNAPSHOT_FILE"
