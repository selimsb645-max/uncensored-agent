#!/usr/bin/env bash
# llama.cpp বিল্ড (সিপিইউ) — ক্যাশ থাকলে দ্রুত
set -euo pipefail
if [ -x "$HOME/llama.cpp/build/bin/llama-server" ]; then
  echo "বিল্ড ক্যাশে থেকে পাওয়া গেছে"; exit 0
fi
git clone --depth 1 https://github.com/ggml-org/llama.cpp "$HOME/llama.cpp"
cd "$HOME/llama.cpp"
cmake -B build -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j"$(nproc)" --target llama-server
