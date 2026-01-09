#!/bin/bash

# --- 1. INSTALL PYTHON DEPENDENCIES FIRST ---
# This fixes "ModuleNotFoundError: No module named 'fastapi'"
echo "📦 Installing requirements (FastAPI, Cython)..."
# We explicitly install cython/wheel/setuptools because setup.py needs them immediately
pip install fastapi uvicorn cython wheel setuptools

# --- 2. PREPARE DIRECTORIES ---
APP_ROOT=$(pwd)
BUILD_DIR="pyav_build"
# This 'lib' folder will hold the FFmpeg shared libraries at runtime
RUNTIME_LIB_DIR="lib" 

mkdir -p $BUILD_DIR
mkdir -p $RUNTIME_LIB_DIR

# --- 3. DOWNLOAD & EXTRACT CUSTOM PYAV ---
URL="https://github.com/vucoffee2310/youtubedownloader/releases/download/pyav-custom/pyav-custom.tar.gz"
FILENAME="pyav-custom.tar.gz"

if [ ! -f "$FILENAME" ]; then
    echo "⬇️ Downloading PyAV source..."
    curl -L -o "$FILENAME" "$URL"
fi

echo "📦 Extracting..."
tar -xf "$FILENAME" -C $BUILD_DIR --strip-components=1

# --- 4. CONFIGURE & COMPILE ---
cd $BUILD_DIR

# Point setup.py to the extracted FFmpeg libraries
# Assuming the tarball contains a 'lib' and 'include' folder
export PKG_CONFIG_PATH="$(pwd)/lib/pkgconfig"
export CFLAGS="-I$(pwd)/include"

# CRITICAL: Overwrite runtime_library_dirs.
# We tell the linker: "Don't look at the build path. Look for libraries 
# in the '../lib' folder relative to where this installed file lives."
export LDFLAGS="-L$(pwd)/lib -Wl,-rpath,'\$ORIGIN/../../lib'"

echo "🔨 Building and Installing PyAV..."
pip install . -v

# --- 5. BUNDLE LIBRARIES FOR RUNTIME ---
cd "$APP_ROOT"

# Copy the .so files (libavcodec, etc) from the build folder to the project root
# so Vercel includes them in the deployment zip.
echo "📋 Copying shared libraries to runtime folder..."
cp -r $BUILD_DIR/lib/*.so* $RUNTIME_LIB_DIR/

# Cleanup to save space
rm -rf $BUILD_DIR $FILENAME
echo "✅ Build Complete."
