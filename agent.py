#!/usr/bin/env python3
"""আনসেন্সরড এজেন্ট — টার্মিনাল চ্যাট।

llama.cpp সার্ভারের (localhost:8080) OpenAI-সামঞ্জস্যপূর্ণ API-তে কথা বলে।
মডেল ফোনেই চলে, ইন্টারনেট লাগে না, কোনো বাইরের ফিল্টার নেই।

    python3 agent.py                 # সাধারণ চ্যাট
    python3 agent.py --system "তুমি একজন রাজনৈতিক লেখক"
    python3 agent.py --temp 0.9      # বেশি সৃজনশীল
"""
import argparse
import json
import os
import sys
import urllib.request

ENDPOINT = os.environ.get("AGENT_ENDPOINT", "http://127.0.0.1:8080/v1/chat/completions")
DEFAULT_SYSTEM = (
    "তুমি একজন সহায়ক বাংলা এজেন্ট। সরাসরি, সৎ আর পূর্ণ উত্তর দাও; "
    "প্রয়োজন হলে ইংরেজিতেও লিখতে পারো। ধর্মীয় বা রাজনৈতিক বিষয়েও তুমি "
    "নিরপেক্ষভাবে তথ্য দাও, কাউকে আঘাত না করে।"
)


def chat(messages, temp=0.7, max_tokens=768):
    body = json.dumps({
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tokens,
        "stream": False,
    }).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default=DEFAULT_SYSTEM)
    ap.add_argument("--temp", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=768)
    a = ap.parse_args()

    messages = [{"role": "system", "content": a.system}]
    print("এজেন্ট তৈরি · /reset দিয়ে নতুন শুরু · /bye দিয়ে বের হন\n")
    while True:
        try:
            q = input("আপনি: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not q:
            continue
        if q in {"/bye", "/exit", "/quit"}:
            break
        if q == "/reset":
            messages = [{"role": "system", "content": a.system}]
            print("(নতুন আলোচনা শুরু)\n")
            continue

        messages.append({"role": "user", "content": q})
        try:
            out = chat(messages, a.temp, a.max_tokens)
        except Exception as e:
            print(f"[ত্রুটি] {type(e).__name__}: {e}")
            messages.pop()
            continue
        messages.append({"role": "assistant", "content": out})
        print(f"\nএজেন্ট: {out}\n")

        # প্রসঙ্গ বাড়তে থাকলে পুরনো অংশ ছেঁটে দিই (RAM বাঁচাতে)
        if len(messages) > 17:
            messages = messages[:1] + messages[-16:]


if __name__ == "__main__":
    sys.exit(main())
