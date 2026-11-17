#!/usr/bin/env python3
"""Telegram থেকে এজেন্ট চালানোর সেতু — এখন কাজ দেখা যায়, থামানোও যায়।

    export TELEGRAM_BOT_TOKEN=xxxxx
    python3 -u telegram.py

কী কী আছে:
- ধাপে ধাপে দেখায়: কোন টুল চলছে, কী ফিরে এল।
- /stop দিলে চলতি কাজ থামে, /reset দিলে কথার মেমোরি মুছে যায়।
- ছবি বা ফাইল পাঠালে সেটা ওয়ার্কস্পেসে নেমে যায়, এজেন্ট সেটা নিয়ে কাজ করতে পারে।
- এজেন্টের send_file টুল দিয়ে সে নিজেই ফাইল/ছবি ফেরত পাঠাতে পারে।
"""
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tools_agent as TA  # noqa: E402
from tools_agent import CFG, agent_turn, system_prompt  # noqa: E402

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED = {x.strip() for x in os.environ.get("TELEGRAM_ALLOWED", "").split(",") if x.strip()}
API = f"https://api.telegram.org/bot{TOKEN}"
MAX_CHARS = CFG["telegram"]["max_chars"]
INBOX = TA.WORKDIR / "inbox"

STOP = threading.Event()
WORK = queue.Queue()
CHATS = {}
OFFSET = 0

TOOL_LABELS = {
    "run_shell": "শেল কমান্ড",
    "write_file": "ফাইল লেখা",
    "read_file": "ফাইল পড়া",
    "list_dir": "ফোল্ডার দেখা",
    "fetch_url": "লিংক পড়া",
    "web_search": "ওয়েবে খোঁজা",
    "download_file": "ফাইল নামানো",
    "send_file": "ফাইল পাঠানো",
    "remember": "মনে রাখা",
}


def _post(method, fields, files=None, timeout=40):
    if files:
        boundary = "----agent" + str(int(time.time() * 1000))
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        for k, (fname, data, ctype) in files.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                     f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{API}/{method}", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(f"{API}/{method}",
                                     data=urllib.parse.urlencode(fields).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        print(f"API {method} ব্যর্থ: {type(e).__name__} {e}", flush=True)
        return None


def send(chat_id, text, reply_to=None):
    fields = {"chat_id": chat_id, "text": (text or "")[:MAX_CHARS]}
    if reply_to:
        fields["reply_to_message_id"] = reply_to
    return _post("sendMessage", fields)


def send_returning(chat_id, text):
    r = send(chat_id, text)
    return (r or {}).get("result", {}).get("message_id")


def edit(chat_id, message_id, text):
    if not message_id:
        return
    _post("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                              "text": (text or "")[:MAX_CHARS]}, timeout=30)


def typing(chat_id):
    _post("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=20)


def send_document(path, caption="", chat_id=None):
    """এজেন্টের send_file টুল এই ফাংশনটাই ডাকে।"""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return f"ফাইল নেই: {p}"
    if p.stat().st_size > 45 * 1024 * 1024:
        return f"ফাইল বড় ({(p.stat().st_size) // (1024 * 1024)} MB), টেলিগ্রামে ৫০ MB-র বেশি যায় না"
    target = chat_id or next(iter(ALLOWED), None)
    data = p.read_bytes()
    ctype = "image/png" if p.suffix.lower() == ".png" else "application/octet-stream"
    method = "sendPhoto" if p.suffix.lower() in (".png", ".jpg", ".jpeg") else "sendDocument"
    key = "photo" if method == "sendPhoto" else "document"
    r = _post(method, {"chat_id": target, "caption": (caption or p.name)[:900]},
              files={key: (p.name, data, ctype)}, timeout=180)
    return f"পাঠানো হয়েছে: {p.name}" if r and r.get("ok") else "পাঠানো যায়নি"


TA.FILE_SENDER = send_document


def get_updates(offset, timeout=25):
    url = f"{API}/getUpdates?" + urllib.parse.urlencode({"offset": offset, "timeout": timeout})
    with urllib.request.urlopen(url, timeout=timeout + 20) as r:
        return json.load(r).get("result", [])


def download_attachment(chat_id, message):
    """মালিক ছবি/ফাইল পাঠালে সেটা ওয়ার্কস্পেসে নামিয়ে পথ ফেরত দেয়।"""
    for key in ("photo", "document", "video", "audio", "voice"):
        if key not in message:
            continue
        item = message[key]
        if key == "photo":
            item = item[-1]
        file_id = item.get("file_id")
        name = item.get("file_name") or f"{key}-{int(time.time())}"
        info = _post("getFile", {"file_id": file_id}, timeout=30) or {}
        path = (info.get("result") or {}).get("file_path")
        if not path:
            return None
        INBOX.mkdir(parents=True, exist_ok=True)
        target = INBOX / Path(name).name
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=180) as r:
                target.write_bytes(r.read())
        except Exception as e:
            print("ফাইল নামানো গেল না:", e, flush=True)
            return None
        return str(target)
    return None


def poller():
    """আলাদা থ্রেডে মেসেজ তোলে, তাই কাজ চলার সময়ও /stop শোনা যায়।"""
    global OFFSET
    while True:
        try:
            ups = get_updates(OFFSET)
        except Exception as e:
            print("আপডেট আনা গেল না:", type(e).__name__, flush=True)
            time.sleep(5)
            continue
        for u in ups:
            OFFSET = u["update_id"] + 1
            msg = u.get("message") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            text = (msg.get("text") or "").strip()
            if chat_id is None:
                continue
            if ALLOWED and str(chat_id) not in ALLOWED:
                send(chat_id, f"এই chat_id অনুমোদিত নয়: {chat_id}")
                continue
            low = text.lower()
            if low in ("/stop", "stop", "/থামো"):
                STOP.set()
                send(chat_id, "থামাচ্ছি… চলতি ধাপটা শেষ হলেই থেমে যাবে।")
                continue
            if low == "/status":
                state = "কাজ চলছে" if not STOP.is_set() and WORK.unfinished_tasks else "ঘুমিয়ে আছে"
                send(chat_id, f"অবস্থা: {state}\nলাইনে: {WORK.qsize()}টি মেসেজ\nওয়ার্কস্পেস: {TA.WORKDIR}")
                continue
            attachment = download_attachment(chat_id, msg) if not text else None
            if not text and not attachment:
                continue
            if attachment and not text:
                text = f"[ফাইল পাঠালাম: {attachment}] এটা দেখে কী করতে হবে বলে দাও, নইলে নিজে যাচাই করে জানাও।"
            elif attachment:
                text = f"[ফাইল: {attachment}]\n{text}"
            WORK.put((chat_id, text))


def start_queued_task(chat_id):
    """লাইনে থাকা কাজ থাকলে রান শুরুতেই একটা নিজে ধরে নেয় (মালিককে জানিয়ে)।"""
    items = TA.load_tasks()
    pending = [x for x in items if not x.get("done")]
    if not pending:
        return False
    task = pending[0]
    task["done"] = True
    TA.save_tasks(items)
    send(chat_id, f"নিজে থেকে ধরলাম: {task.get('text', '')[:400]}\n(শেষ হলে জানাব)")
    WORK.put((chat_id, f"[নিজে থেকে করা কাজ] {task.get('text', '')}"))
    return True


def history(chat_id):
    return CHATS.setdefault(chat_id, [{"role": "system", "content": system_prompt("chat")}])


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN নেই — BotFather থেকে টোকেন নিয়ে export করুন")
    print("Telegram সেতু চালু (টুলসহ)।", flush=True)
    threading.Thread(target=poller, daemon=True).start()
    if ALLOWED:
        try:
            start_queued_task(next(iter(ALLOWED)))
        except Exception as e:
            print("লাইনে থাকা কাজ শুরু করা গেল না:", type(e).__name__, flush=True)
    while True:
        chat_id, text = WORK.get()
        if text.strip() == "/reset":
            CHATS.pop(chat_id, None)
            send(chat_id, "কথার মেমোরি মুছে ফেলেছি।")
            WORK.task_done()
            continue
        STOP.clear()
        hist = history(chat_id)
        hist.append({"role": "user", "content": text})
        limit = CFG["telegram"]["history_messages"]
        if len(hist) > limit + 1:
            hist[:] = hist[:1] + hist[-limit:]
        mid = send_returning(chat_id, "…")
        typing(chat_id)
        started = time.time()

        def on_token(partial):
            if not mid or not CFG["telegram"].get("stream", True):
                return
            if time.time() - started < 3:
                return
            edit(chat_id, mid, partial + " ▌")

        def on_step(kind, name, detail):
            label = TOOL_LABELS.get(name, name)
            if kind == "start":
                edit(chat_id, mid, f"⚙ {label} চলছে…\n{detail[:800]}")
                typing(chat_id)
            elif kind == "done":
                head = detail.strip().split("\n")[0][:300]
                edit(chat_id, mid, f"⚙ {label} শেষ\n{head}\n\nবাকিটা ভাবছি…")

        try:
            out = agent_turn(hist, CFG["temperature"], on_token, on_step, STOP.is_set)
        except Exception as e:
            out = f"ত্রুটি: {type(e).__name__}: {e}"
        hist.append({"role": "assistant", "content": out})
        if mid:
            edit(chat_id, mid, out or "(কোনো উত্তর আসেনি)")
        else:
            send(chat_id, out or "(কোনো উত্তর আসেনি)")
        print(f"উত্তর দেওয়া হলো ({time.time() - started:.1f}s)", flush=True)
        WORK.task_done()


if __name__ == "__main__":
    sys.exit(main())
