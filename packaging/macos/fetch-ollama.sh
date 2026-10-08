#!/bin/bash
# Ollama bundled in the app (the App Store forbids downloading code): a pinned, checked release,
# reduced to what Apple silicon uses with GGUF models (the arm64 `ollama` and `llama-server`, no
# Intel libraries nor MLX engine: 36 MB instead of 490), with its licenses.
set -euo pipefail

VERSION=v0.34.3
SHA256=2c45865f94bce0d4d1d2567603dd2fdacaf375585220a175aa4800105193d36e
TARGET="${1:?usage: fetch-ollama.sh <folder>}"

if [ -x "$TARGET/ollama" ] && [ "$(cat "$TARGET/VERSION" 2>/dev/null)" = "$VERSION" ]; then
  exit 0
fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
curl -fsSL -o "$work/ollama-darwin.tgz" "https://github.com/ollama/ollama/releases/download/$VERSION/ollama-darwin.tgz"
echo "$SHA256  $work/ollama-darwin.tgz" | shasum -a 256 -c --quiet
mkdir -p "$work/x"
tar -xzf "$work/ollama-darwin.tgz" -C "$work/x"
rm -rf "$TARGET"
mkdir -p "$TARGET/licenses"
for binary in ollama llama-server; do
  lipo -thin arm64 "$work/x/$binary" -output "$TARGET/$binary"
done
cp "$work/x/"*LICENSE* "$work/x/"*NOTICE* "$TARGET/licenses/"
echo "$VERSION" > "$TARGET/VERSION"
