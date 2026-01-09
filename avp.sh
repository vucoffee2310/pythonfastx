#!/bin/bash

# Configuration
URL="https://github.com/vucoffee2310/youtubedownloader/releases/download/pyav-custom/pyav-custom.tar.gz"
FILENAME="pyav-custom.tar.gz"
DIRNAME="pyav"

# --- 0. SETUP PYTHON ALIAS (python-is-python3) ---
# This simulates 'apt install python-is-python3' without needing root
if ! command -v python >/dev/null 2>&1; then
    echo "🔗 'python' command not found. Linking python -> python3..."
    # Create a local bin directory
    mkdir -p "$PWD/local_bin"
    # Symlink python3 to python inside it
    ln -s "$(which python3)" "$PWD/local_bin/python"
    # Add to PATH for the duration of this script
    export PATH="$PWD/local_bin:$PATH"
    echo "✅ Python alias setup complete: $(python --version)"
fi

# --- 1. INSTALL BUILD DEPENDENCIES ---
# PyAV requires Cython to build from source
echo "📦 Installing build dependencies..."
pip install cython wheel setuptools

# --- 2. PREVENT DOUBLE INSTALL ---
if [ -d "$DIRNAME/lib" ] && pip show av >/dev/null 2>&1; then
    echo "✅ [CACHE HIT] 'av' is installed and libs exist. Skipping build."
    exit 0
fi

# --- 3. DOWNLOAD & EXTRACT ---
if [ ! -d "$DIRNAME" ]; then
    echo "⬇️ Downloading custom PyAV archive..."
    if [ ! -f "$FILENAME" ]; then
        curl -L -o "$FILENAME" "$URL"
    fi
    echo "📦 Extracting..."
    tar -xf "$FILENAME"
fi

# --- 4. CONFIGURE, MAKE, & INSTALL ---
if [ -d "$DIRNAME" ]; then
    cd "$DIRNAME" || exit 1
    LOCAL_ROOT="$(pwd)"
    
    echo "⚙️ Setting Build Paths..."
    export PKG_CONFIG_PATH="$LOCAL_ROOT/lib/pkgconfig:$PKG_CONFIG_PATH"
    export LD_LIBRARY_PATH="$LOCAL_ROOT/lib:$LD_LIBRARY_PATH"
    export CFLAGS="-I$LOCAL_ROOT/include"
    
    # CRITICAL: Add rpath so the binary remembers where to find libs relative to itself
    export LDFLAGS="-L$LOCAL_ROOT/lib -Wl,-rpath,'$LOCAL_ROOT/lib'"

    echo "🔨 Running 'make' (if Makefile exists)..."
    # Now 'make' will use 'python' (which points to python3) if it calls it internally
    make || echo "⚠️ Make skipped or failed (proceeding to pip)..."

    echo "🚀 Running 'pip install .'..."
    pip install . -v 
    INSTALL_STATUS=$?

    cd ..

    # --- 5. CLEANUP ---
    if [ $INSTALL_STATUS -eq 0 ]; then
        echo "✅ Installation successful."
        # Clean up heavy folders, BUT KEEP 'lib'
        rm -rf "$DIRNAME/include" "$DIRNAME/src" "$DIRNAME/examples" "$DIRNAME/docs" "$FILENAME" "$PWD/local_bin"
    else
        echo "❌ Installation failed."
        exit 1
    fi

else
    echo "❌ Error: Folder '$DIRNAME' not found."
    exit 1
fi
