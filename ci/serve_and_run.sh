#!/usr/bin/env bash
# সার্ভার তোলে, তারপর Telegram থেকে প্রশ্নের উত্তর দিতে থাকে
set -uo pipefail
MODEL="$PWD/models/${MODEL_FILE:?MODEL_FILE নেই}"
"$HOME/llama.cpp/build/bin/llama-server" \
  -m "$MODEL" --port 8080 -c 4096 -t "$(nproc)" --jinja > llama-server.log 2>&1 &
SRV=$!
for i in $(seq 1 180); do
  curl -s --max-time 2 http://127.0.0.1:8080/health >/dev/null 2>&1 && { echo "সার্ভার তৈরি (${i}0s)"; break; }
  sleep 10
done
tail -5 llama-server.log || true
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "টোকেন নেই — একবার পরীক্ষার প্রশ্ন পাঠাচ্ছি"
  curl -s --max-time 600 http://127.0.0.1:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"বাংলায় এক লাইনে বলো: তুমি কে?"}],"max_tokens":120,"temperature":0.6}' \
    | python3 -c "import sys,json;print('উত্তর:', json.load(sys.stdin)['choices'][0]['message']['content'].strip())"
else
  timeout 17000 python3 telegram.py || true
fi
kill "$SRV" 2>/dev/null || true
