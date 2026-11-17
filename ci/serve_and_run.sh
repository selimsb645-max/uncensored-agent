#!/usr/bin/env bash
# সার্ভার তোলে, ওয়ার্কস্পেস ফিরিয়ে আনে, তারপর Telegram থেকে কাজ করতে থাকে।
# শেষে ওয়ার্কস্পেস + মেমোরি agent-state ব্রাঞ্চে রেখে যায়, তাই রিস্টার্টেও হারায় না।
set -uo pipefail

WORK="${AGENT_WORKDIR:-$HOME/agent-work}"
STATE_BRANCH="${STATE_BRANCH:-agent-state}"
mkdir -p "$WORK"

restore_state() {
  if git ls-remote --heads origin "$STATE_BRANCH" 2>/dev/null | grep -q "$STATE_BRANCH"; then
    git fetch --depth=1 origin "$STATE_BRANCH" -q 2>/dev/null || true
    if git show "FETCH_HEAD:state.tar.gz" > /tmp/state.tar.gz 2>/dev/null; then
      tar -xzf /tmp/state.tar.gz -C "$WORK" 2>/dev/null \
        && echo "আগের ওয়ার্কস্পেস ফিরে এসেছে: $(find "$WORK" -type f | wc -l)টি ফাইল"
    fi
  else
    echo "প্রথম রান — পুরোনো ওয়ার্কস্পেস নেই"
  fi
}

persist_state() {
  [ -d "$WORK" ] || return 0
  tar -czf /tmp/state.tar.gz -C "$WORK" \
    --exclude='node_modules' --exclude='*.gguf' --exclude='*.bin' --exclude='.git' . 2>/dev/null || return 0
  local size
  size=$(stat -c%s /tmp/state.tar.gz 2>/dev/null || echo 0)
  echo "ওয়ার্কস্পেস সংরক্ষণ: $((size/1024)) KB"
  local tmp
  tmp=$(mktemp -d)
  (
    cd "$tmp" || exit 0
    git init -q
    git config user.email "agent@users.noreply.github.com"
    git config user.name "solas-agent"
    cp /tmp/state.tar.gz state.tar.gz
    git add state.tar.gz
    git commit -q -m "state $(date -u +%FT%TZ)"
    git push -f -q "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" \
      HEAD:"$STATE_BRANCH" && echo "ওয়ার্কস্পেস সংরক্ষণ হয়েছে ($STATE_BRANCH)"
  )
}

restore_state
trap persist_state EXIT

MODEL="$PWD/models/${MODEL_FILE:?MODEL_FILE নেই}"
"$HOME/llama.cpp/build/bin/llama-server" \
  -m "$MODEL" --port 8080 -c "${AGENT_CONTEXT:-4096}" -t "$(nproc)" --jinja > llama-server.log 2>&1 &
SRV=$!
for i in $(seq 1 180); do
  curl -s --max-time 2 http://127.0.0.1:8080/health >/dev/null 2>&1 && { echo "সার্ভার তৈরি (${i}0s)"; break; }
  sleep 10
done
tail -5 llama-server.log || true

# টুল ঠিকঠাক চলছে কি না, প্রতিটি রানেই একবার যাচাই (লগে দেখা যাবে)
if [ "${AGENT_SELFTEST:-1}" = "1" ]; then
  echo "টুল সেলফ-টেস্ট চলছে…"
  AGENT_WORKDIR="$WORK" timeout 420 python3 -u ci/selftest.py || true
fi

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "টোকেন নেই — একবার পরীক্ষার প্রশ্ন পাঠাচ্ছি"
  curl -s --max-time 600 http://127.0.0.1:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"messages":[{"role":"user","content":"বাংলায় এক লাইনে বলো: তুমি কে?"}],"max_tokens":120,"temperature":0.6}' \
    | python3 -c "import sys,json;print('উত্তর:', json.load(sys.stdin)['choices'][0]['message']['content'].strip())"
else
  # -u না দিলে লগে কিছুই দেখা যায় না (আউটপুট বাফারে আটকে থাকে)
  timeout 17000 python3 -u telegram.py || true
fi

kill "$SRV" 2>/dev/null || true
echo "রান শেষ"
