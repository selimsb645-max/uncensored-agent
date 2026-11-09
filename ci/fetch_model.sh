#!/usr/bin/env bash
# মডেল নামায় (একবার; পরে GitHub cache থেকে আসবে)
set -euo pipefail
mkdir -p models
case "${MODEL_TIER:-14b}" in
  7b)  REPO="mradermacher/Qwen2.5-7B-Instruct-abliterated-GGUF"; FILE="Qwen2.5-7B-Instruct-abliterated.Q4_K_M.gguf" ;;
  32b) REPO="mradermacher/Qwen2.5-32B-Instruct-abliterated-GGUF"; FILE="Qwen2.5-32B-Instruct-abliterated.Q4_K_M.gguf" ;;
  *)   REPO="mradermacher/Qwen2.5-14B-Instruct-abliterated-GGUF"; FILE="Qwen2.5-14B-Instruct-abliterated.Q4_K_M.gguf" ;;
esac
echo "MODEL_FILE=$FILE" >> "$GITHUB_ENV"
if [ -f "models/$FILE" ]; then
  echo "মডেল আগেই আছে: $FILE ($(du -h "models/$FILE" | cut -f1))"
else
  echo "নামানো হচ্ছে: $FILE"
  curl -L --retry 3 --retry-delay 5 -o "models/$FILE" \
    "https://huggingface.co/$REPO/resolve/main/$FILE"
fi
ls -lh models/
