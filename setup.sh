#!/data/data/com.termux/files/usr/bin/bash
# আনসেন্সরড এজেন্ট — ফোনে একবার সেটআপ। Termux-এ: bash setup.sh
set -e
echo "== ১/৪ প্যাকেজ =="
pkg update -y
pkg install -y git cmake ninja clang python curl

echo "== ২/৪ llama.cpp =="
cd ~
[ -d llama.cpp ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j4 --target llama-server llama-cli

echo "== ৩/৪ মডেল (~২ GB) =="
mkdir -p ~/models && cd ~/models
MODEL=Qwen2.5-3B-Instruct-abliterated.Q4_K_M.gguf
[ -f "$MODEL" ] || curl -L --progress-bar -o "$MODEL" \
  "https://huggingface.co/mradermacher/Qwen2.5-3B-Instruct-abliterated-GGUF/resolve/main/Qwen2.5-3B-Instruct-abliterated.Q4_K_M.gguf"

echo "== ৪/৪ শেষ =="
ls -lh ~/models/"$MODEL"
echo "এখন চালান: bash ~/uncensored-agent/start.sh"
