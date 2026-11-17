#!/usr/bin/env python3
"""প্রতি রানে একবারের টুল পরীক্ষা: মডেল সত্যিই টুল ডাকছে কি না, ফল ফিরছে কি না।

লগে "সেলফ-টেস্ট ধাপ:" আর "সেলফ-টেস্ট উত্তর:" দেখা যাবে। মডেল সার্ভার আগেই
ওঠানো থাকে (ci/serve_and_run.sh), তাই এখানে শুধু এক টার্ন চালানো হয়।
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools_agent as TA  # noqa: E402

PROMPT = "শেল দিয়ে date -u চালিয়ে এক লাইনে বলো।"

# রানারে CPU-তে মডেল ধীর, তাই সেলফ-টেস্ট ছোট রাখা হয়
TA.MAX_STEPS = 2
TA.CFG["max_tokens"] = 220

steps = []


def on_step(kind, name, detail):
    steps.append(f"{kind}:{name}")
    print(f"  ⚙ {kind} {name} :: {detail[:160]}", flush=True)


def main():
    messages = [
        {"role": "system", "content": TA.system_prompt("chat")},
        {"role": "user", "content": PROMPT},
    ]
    try:
        out = TA.agent_turn(messages, 0.4, None, on_step, lambda: False)
    except Exception as e:
        print("সেলফ-টেস্ট ব্যর্থ:", type(e).__name__, e, flush=True)
        return 1
    used_tool = any(s.startswith("start:") for s in steps)
    print("সেলফ-টেস্ট ধাপ:", steps, flush=True)
    print("সেলফ-টেস্ট টুল ব্যবহার:", "হ্যাঁ" if used_tool else "না", flush=True)
    print("সেলফ-টেস্ট উত্তর:", (out or "")[:500], flush=True)
    if not used_tool:
        alert("সতর্কতা: টুল সেলফ-টেস্টে মডেল টুল ডাকেনি।\nউত্তর: " + (out or "")[:300]
              + "\nলগ: https://github.com/selimsb645-max/uncensored-agent/actions")
    return 0 if used_tool else 2


def alert(text):
    """কেবল সমস্যা হলে মালিককে টেলিগ্রামে জানানো হয়।"""
    import json as _json
    import urllib.parse
    import urllib.request
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = (os.environ.get("TELEGRAM_ALLOWED", "").split(",") or [""])[0].strip()
    if not token or not chat:
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:1500]}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30).read()
    except Exception as e:
        print("সতর্কবার্তা পাঠানো গেল না:", type(e).__name__, flush=True)


if __name__ == "__main__":
    sys.exit(main())
