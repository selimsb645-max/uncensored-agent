#!/data/data/com.termux/files/usr/bin/bash
# মডেল সার্ভার চালু করে, তারপর চ্যাট খোলে।
set -u
termux-wake-lock 2>/dev/null || true
MODEL="$HOME/models/Qwen2.5-3B-Instruct-abliterated.Q4_K_M.gguf"
PORT=8080
[ -f "$MODEL" ] || { echo "মডেল নেই — আগে bash setup.sh চালান"; exit 1; }

# সার্ভার আগে থেকে চললে নতুন করে চালাই না
if ! curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "মডেল লোড হচ্ছে (একবারই, ৩০-৬০ সেকেন্ড)..."
  nohup "$HOME/llama.cpp/build/bin/llama-server" \
    -m "$MODEL" --port $PORT -c 4096 -t 4 --jinja \
    > "$HOME/llama-server.log" 2>&1 &
  for i in $(seq 1 90); do
    curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
    sleep 2
  done
fi
python3 "$(dirname "$0")/agent.py"
