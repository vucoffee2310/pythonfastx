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
# Vercel includes this folder in the deployment bundle.
mkdir -p bin

# 2. INSTALL TREE (Install via yum, then grab the binary)
if command -v yum &> /dev/null; then
    echo "🌲 Installing Tree via yum..."
    yum install -y tree
    cp $(which tree) bin/
else
    echo "⚠️  Yum not found, skipping tree system install."
fi

# 3. INSTALL JQ (Download Static Binary)
echo "🦆 Downloading Static JQ..."
curl -L -o bin/jq https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-linux-amd64
chmod +x bin/jq

# 4. INSTALL DENO (Required for yt-dlp signature/PO Token)
echo "🦕 Installing Deno..."
# Standard Deno install script
curl -fsSL https://deno.land/install.sh | sh

# Move Deno from default home loc to our project bin
echo "🚚 Moving Deno binary to ./bin/..."
if [ -f "$HOME/.deno/bin/deno" ]; then
    cp "$HOME/.deno/bin/deno" bin/
    chmod +x bin/deno
    # Clean up to save space in the lambda slug
    rm -rf "$HOME/.deno"
    echo "✅ Deno installed successfully."
else
    echo "❌ Error: Deno binary not found after install s
