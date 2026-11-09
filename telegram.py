#!/usr/bin/env python3
"""Telegram থেকে এজেন্ট চালানোর সেতু।

    export TELEGRAM_BOT_TOKEN=xxxxx
    python3 telegram.py

শুধু আপনার নিজের chat_id কাজ করবে (প্রথমবার /start দিলে সেটা দেখিয়ে দেয়)।
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools_agent import CFG, agent_turn, system_prompt  # noqa: E402

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = {x.strip() for x in os.environ.get("TELEGRAM_ALLOWED", "").split(",") if x.strip()}
API = f"https://api.telegram.org/bot{TOKEN}"


def send(chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:CFG["telegram"]["max_chars"]]}).encode()
    try:
        urllib.request.urlopen(f"{API}/sendMessage", data=data, timeout=40).read()
    except Exception as e:
        print("পাঠাতে পারিনি:", type(e).__name__, e)


def edit(chat_id, message_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "message_id": message_id,
                                   "text": text[:CFG["telegram"]["max_chars"]]}).encode()
    try:
        urllib.request.urlopen(f"{API}/editMessageText", data=data, timeout=30).read()
    except Exception:
        pass


def send_returning(chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:CFG["telegram"]["max_chars"]]}).encode()
    try:
        r = urllib.request.urlopen(f"{API}/sendMessage", data=data, timeout=30)
        return json.load(r).get("result", {}).get("message_id")
    except Exception:
        return None


def get_updates(offset):
    url = f"{API}/getUpdates?" + urllib.parse.urlencode({"offset": offset, "timeout": 40})
    with urllib.request.urlopen(url, timeout=70) as r:
        return json.load(r).get("result", [])


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN নেই — BotFather থেকে টোকেন নিয়ে export করুন")
    print("Telegram সেতু চালু। বন্ধ করতে Ctrl-C।")
    offset, chats = 0, {}
    while True:
        try:
            ups = get_updates(offset)
        except Exception as e:
            print("আপডেট আনা গেল না:", type(e).__name__)
            time.sleep(5)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat_id = (msg.get("chat") or {}).get("id")
            if not text or not chat_id:
                continue
            if ALLOWED and str(chat_id) not in ALLOWED:
                send(chat_id, f"এই chat_id অনুমোদিত নয়: {chat_id}")
                continue
            if text == "/start":
                send(chat_id, f"এজেন্ট তৈরি। আপনার chat_id: {chat_id}\nএটা TELEGRAM_ALLOWED-এ রাখলে অন্যদের আটকানো যাবে।")
                continue
            hist = chats.setdefault(chat_id, [{"role": "system", "content": system_prompt("chat")}])
            hist.append({"role": "user", "content": text})
            # স্ট্রিমিং: প্রথম শব্দের জন্য অপেক্ষা না করে লেখা আসার সাথে সাথে দেখায়
            mid = send_returning(chat_id, "…")
            last = {"t": 0.0, "sent": ""}

            def on_token(partial):
                if not mid or not CFG["telegram"].get("stream", True):
                    return
                now = time.time()
                if now - last["t"] < CFG["telegram"].get("edit_every_sec", 2.0):
                    return
                last["t"] = now
                last["sent"] = partial
                edit(chat_id, mid, partial + " ▌")

            try:
                out = agent_turn(hist, CFG["temperature"], on_token)
            except Exception as e:
                send(chat_id, f"ত্রুটি: {type(e).__name__}")
                continue
            hist.append({"role": "assistant", "content": out})
            limit = CFG["telegram"]["history_messages"]
            if len(hist) > limit + 1:
                hist[:] = hist[:1] + hist[-limit:]
            if mid:
                edit(chat_id, mid, out or "(কোনো উত্তর আসেনি)")
            else:
                send(chat_id, out or "(কোনো উত্তর আসেনি)")


if __name__ == "__main__":
    sys.exit(main())
