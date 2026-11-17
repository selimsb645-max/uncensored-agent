#!/usr/bin/env python3
"""সোলাস-ধাঁচের এজেন্ট, কিন্তু আনসেন্সরড — টুলসহ।

যা আছে: মডেল (llama.cpp), টুল (শেল, ফাইল, ওয়েব, মেমোরি, ফাইল পাঠানো), আর একটা
লুপ যেটা নিজে ঠিক করে কোন টুল লাগবে। এজেন্ট যা করে সব ধাপে ধাপে দেখা যায়।

    python3 tools_agent.py                 # টার্মিনালে
    python3 tools_agent.py --preset writer

গুরুত্বপূর্ণ: টুল চলার সময় এনভায়রনমেন্ট পরিষ্কার করে দেওয়া হয় (SAFE_ENV), তাই
শেলের ভেতর থেকে বটের টোকেন বা GitHub secret পড়া যায় না।
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent


def load_config():
    """config.json-এর সব সেটিং; না পেলে নিরাপদ ডিফল্ট।"""
    defaults = {"temperature": 0.6, "max_tokens": 900, "max_steps": 8,
                "memory_limit": 200, "memory_in_prompt": 20, "language": "bn",
                "base_prompt": "solas_prompt.md", "workdir": "~/agent-work",
                "max_output": 6000, "shell_timeout": 240}
    try:
        cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
        defaults.update(cfg)
    except Exception:
        pass
    return defaults


CFG = load_config()
ENDPOINT = os.environ.get("AGENT_ENDPOINT", "http://127.0.0.1:8080/v1/chat/completions")
WORKDIR = Path(os.path.expanduser(os.environ.get("AGENT_WORKDIR", CFG["workdir"])))
MAX_STEPS = CFG["max_steps"]
MAX_OUTPUT = int(CFG.get("max_output", 6000))
SHELL_TIMEOUT = int(CFG.get("shell_timeout", 240))
MEMORY = WORKDIR / "memory.json"
LEARNED = WORKDIR / "learnings.md"
TOOLDIR = WORKDIR / "tools"
TASKS = WORKDIR / "tasks.json"

# টেলিগ্রাম স্তর এখানে ফাংশন বসায়, তখন এজেন্ট মালিককে ফাইল পাঠাতে পারে
FILE_SENDER = None

# টুল চলার সময় শুধু এই ভেরিয়েবলগুলো থাকবে — বটের টোকেন, GITHUB_TOKEN কিছুই না
_KEEP_ENV = {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TERM", "USER", "SHELL",
             "PYTHONUNBUFFERED", "PYTHONIOENCODING", "AGENT_WORKDIR",
             "AGENT_ENDPOINT", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}

TOOLS = [
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "লিনাক্স সার্ভারে একটা শেল কমান্ড চালায় (ঘণ্টা না, মিনিট)। "
                       "ফাইল, পাইথন, git, curl, ffmpeg — যা দরকার চালানো যায়।",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "চালানোর কমান্ড"},
            "timeout": {"type": "integer", "description": "সর্বোচ্চ সেকেন্ড, ডিফল্ট ২৪০"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "ওয়ার্কস্পেসে একটা ফাইল লেখে (নতুন ফোল্ডারও বানায়)। কোড বা লেখা বানাতে এটা ব্যবহার করো।",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "একটা ফাইলের লেখা পড়ে।",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "ফোল্ডারে কী কী ফাইল আছে দেখায় (নাম, আকার)।",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "খালি রাখলে ওয়ার্কস্পেস"}}}},
    },
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "একটা URL থেকে লেখা (HTML/JSON) নিয়ে আসে।",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "ওয়েবে সার্চ করে শিরোনাম, লিংক আর ছোট সারাংশ দেয়।",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "download_file",
        "description": "ইন্টারনেট থেকে ফাইল (ছবি, ভিডিও, pdf) ওয়ার্কস্পেসে নামায়।",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"},
            "path": {"type": "string", "description": "যেমন downloads/clip.mp4"}},
            "required": ["url", "path"]}}},
    {"type": "function", "function": {
        "name": "send_file",
        "description": "ওয়ার্কস্পেসের একটা ফাইল সোজা মালিকের টেলিগ্রামে পাঠায় (ছবি বা ডকুমেন্ট)।",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "caption": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "learn",
        "description": "নিজের জন্য একটা শিক্ষা লিখে রাখে (কী কাজ করল, কী ব্যর্থ হল, কীভাবে ঠিক হল)। "
                       "পরের রানেও এটা পড়ে নিজে উন্নতি করবে।",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "make_tool",
        "description": "নিজের জন্য নতুন টুল (পাইথন স্ক্রিপ্ট) বানিয়ে সংরক্ষণ করে। পরে "
                       "run_shell দিয়ে `python3 tools/<নাম>.py` চালানো যাবে। কাজ বারবার লাগলে এটা ব্যবহার করো।",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "ইংরেজি ছোট নাম, যেমন resize_image"},
            "description": {"type": "string", "description": "কী করে, কীভাবে চালাতে হয়"},
            "code": {"type": "string", "description": "পুরো পাইথন কোড"}},
            "required": ["name", "code"]}}},
    {"type": "function", "function": {
        "name": "add_task",
        "description": "পরে নিজে নিজে করার জন্য একটা কাজ লাইনে রাখে (রিস্টার্টের পরও থাকবে)।",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "ভবিষ্যতের জন্য একটা স্থায়ী তথ্য মেমোরিতে রাখে (পছন্দ, নিয়ম, সিদ্ধান্ত)।",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
]

# এই ধরনের কমান্ড নিজে থেকে চালানো হয় না, মালিকের স্পষ্ট সম্মতি লাগে
DANGER_PATTERNS = [
    (r"\brm\s+-[a-z]*r[a-z]*f?\s+(/|~|\$HOME)\s*($|\*)", "পুরো ফাইল সিস্টেম মুছে ফেলা"),
    (r"\brm\s+-[a-z]*r[a-z]*f?\s+/\s", "সিস্টেম ফোল্ডার মুছে ফেলা"),
    (r"\bmkfs\b", "ডিস্ক ফরম্যাট"),
    (r"\bdd\b.*of=/dev/", "ডিস্কে সরাসরি লেখা"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "সার্ভার বন্ধ করা"),
    (r":\(\)\s*\{.*\};?\s*:", "ফর্ক বোমা"),
    (r"\bchmod\s+-R\s+777\s+/\s*$", "পুরো সিস্টেমে খোলা পারমিশন"),
    (r"\bgit\s+push\b.*(--force|-f)\b", "জোর করে পুশ করা"),
    (r">\s*/dev/sd", "ডিস্কে রিডাইরেক্ট"),
]


def safe_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k in _KEEP_ENV}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.setdefault("HOME", os.path.expanduser("~"))
    env["PYTHONUNBUFFERED"] = "1"
    if extra:
        env.update(extra)
    return env


def dangerous(command):
    for pattern, why in DANGER_PATTERNS:
        if re.search(pattern, command):
            return why
    return None


def load_learnings(limit=40):
    try:
        lines = [ln.strip() for ln in LEARNED.read_text(encoding="utf-8").split("\n") if ln.strip().startswith("- ")]
        return lines[-limit:]
    except Exception:
        return []


def append_learning(text):
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    with open(LEARNED, "a", encoding="utf-8") as f:
        f.write(f"- {text.strip()}\n")


def load_tasks():
    try:
        return json.loads(TASKS.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_tasks(items):
    TASKS.parent.mkdir(parents=True, exist_ok=True)
    TASKS.write_text(json.dumps(items[-100:], ensure_ascii=False, indent=1), encoding="utf-8")


def load_memory():
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_memory(items):
    MEMORY.parent.mkdir(parents=True, exist_ok=True)
    MEMORY.write_text(json.dumps(items[-CFG["memory_limit"]:], ensure_ascii=False, indent=1), encoding="utf-8")


def _short(text, limit=MAX_OUTPUT):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…(বাকিটা কাটা, মোট {len(text)} অক্ষর)"


UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _clean(html):
    return re.sub(r"<[^>]+>", "", html).replace("&amp;", "&").replace("&#x27;", "'").strip()


def web_search(query, limit=6):
    """DuckDuckGo থেকে ফলাফল (কোনো API key লাগে না)। দুটো মার্কআপই চেষ্টা করা হয়।"""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        html = r.read(400000).decode("utf-8", "replace")
    items, seen = [], set()
    patterns = [r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                r'href="([^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>',
                r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>']
    for pattern in patterns:
        for m in re.finditer(pattern, html, re.S):
            href, title = m.group(1), _clean(m.group(2))
            href = urllib.parse.unquote(href)
            if "uddg=" in href:
                href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
            if not href.startswith("http") or "duckduckgo.com" in href or href in seen:
                continue
            seen.add(href)
            items.append(f"{title}\n{href}" if title else href)
            if len(items) >= limit:
                break
        if items:
            break
    if items:
        return "\n\n".join(items)
    text = re.sub(r"\s+", " ", _clean(html))[:800]
    return f"(সার্চে কিছু পাওয়া যায়নি, পাতার লেখা: {text})"


def run_tool(name, args):
    try:
        if name == "run_shell":
            command = str(args.get("command", "")).strip()
            if not command:
                return "কমান্ড খালি"
            why = dangerous(command)
            if why:
                return (f"⛔ এই কমান্ডটা চালাইনি ({why})। এটা ধ্বংসাত্মক — "
                        f"মালিকের স্পষ্ট অনুমতি ছাড়া করব না, আগে তাঁকে জিজ্ঞেস করো।")
            WORKDIR.mkdir(parents=True, exist_ok=True)
            timeout = int(args.get("timeout") or SHELL_TIMEOUT)
            timeout = max(10, min(timeout, 900))
            r = subprocess.run(command, shell=True, capture_output=True, text=True,
                               timeout=timeout, cwd=WORKDIR, env=safe_env())
            out = (r.stdout or "")
            if r.stderr:
                out += "\n[stderr] " + r.stderr
            if r.returncode != 0:
                out += f"\n(exit {r.returncode})"
            return _short(out.strip()) or f"(exit {r.returncode}, কোনো আউটপুট নেই)"
        if name == "write_file":
            p = Path(os.path.expanduser(str(args["path"])))
            if not p.is_absolute():
                p = WORKDIR / p
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(args.get("content", "")), encoding="utf-8")
            return f"লেখা হয়েছে: {p} ({len(str(args.get('content', '')))} অক্ষর)"
        if name == "read_file":
            p = Path(os.path.expanduser(str(args["path"])))
            if not p.is_absolute():
                p = WORKDIR / p
            return _short(p.read_text(encoding="utf-8", errors="replace"))
        if name == "list_dir":
            p = Path(os.path.expanduser(str(args.get("path") or "")))
            if not str(p) or str(args.get("path", "")).strip() in ("", "."):
                p = WORKDIR
            elif not p.is_absolute():
                p = WORKDIR / p
            p.mkdir(parents=True, exist_ok=True)
            rows = []
            for item in sorted(p.iterdir())[:200]:
                rows.append(f"{'📁' if item.is_dir() else '📄'} {item.name}"
                            + ("" if item.is_dir() else f"  {item.stat().st_size} B"))
            return "\n".join(rows) or "(ফোল্ডার খালি)"
        if name == "fetch_url":
            req = urllib.request.Request(str(args["url"]), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read(300000).decode("utf-8", "replace")
            return _short(body)
        if name == "web_search":
            return _short(web_search(str(args.get("query", ""))))
        if name == "download_file":
            target = Path(os.path.expanduser(str(args["path"])))
            if not target.is_absolute():
                target = WORKDIR / target
            target.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(str(args["url"]), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(target, "wb") as f:
                f.write(r.read(80 * 1024 * 1024))
            return f"নেমেছে: {target} ({target.stat().st_size} B)"
        if name == "send_file":
            p = Path(os.path.expanduser(str(args["path"])))
            if not p.is_absolute():
                p = WORKDIR / p
            if not p.exists():
                return f"ফাইল নেই: {p}"
            if FILE_SENDER is None:
                return "এখান থেকে ফাইল পাঠানো যায় না (শুধু টেলিগ্রাম থেকে চালালে কাজ করে)"
            return FILE_SENDER(str(p), str(args.get("caption") or ""))
        if name == "learn":
            append_learning(str(args.get("text", "")))
            return "শেখা হিসেবে রাখা হলো"
        if name == "make_tool":
            slug = re.sub(r"[^a-z0-9_]", "_", str(args.get("name", "")).strip().lower())[:40] or "tool"
            TOOLDIR.mkdir(parents=True, exist_ok=True)
            target = TOOLDIR / f"{slug}.py"
            target.write_text(str(args.get("code", "")), encoding="utf-8")
            os.chmod(target, 0o755)
            append_learning(f"টুল `{slug}` বানানো হয়েছে ({str(args.get('description', ''))[:80]}), চালাতে: python3 tools/{slug}.py")
            return f"টুল তৈরি: {target} — চালাতে: python3 tools/{slug}.py"
        if name == "add_task":
            items = load_tasks()
            items.append({"text": str(args.get("text", "")).strip(), "done": False})
            save_tasks(items)
            return "কাজ লাইনে রাখা হলো"
        if name == "remember":
            items = load_memory()
            items.append(str(args.get("text", "")).strip())
            save_memory([x for x in items if x])
            return "মনে রাখা হলো"
        return f"অজানা টুল: {name}"
    except subprocess.TimeoutExpired:
        return f"⏱ কমান্ডটা {SHELL_TIMEOUT} সেকেন্ডে শেষ হয়নি, থামিয়ে দিয়েছি"
    except Exception as e:
        return f"টুল ব্যর্থ: {type(e).__name__}: {e}"


def call_model(messages, temp=0.6, on_token=None):
    """মডেলকে ডাকে। on_token দিলে উত্তর লেখার সাথে সাথে টুকরো টুকরো পাঠায়।"""
    payload = {"messages": messages, "temperature": temp,
               "max_tokens": CFG["max_tokens"], "tools": TOOLS, "tool_choice": "auto"}
    if on_token:
        payload["stream"] = True
    req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        if not on_token:
            return json.load(r)["choices"][0]["message"]
        content, calls = "", {}
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                delta = json.loads(chunk)["choices"][0].get("delta") or {}
            except Exception:
                continue
            if delta.get("content"):
                content += delta["content"]
                on_token(content)
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0),
                                        {"id": "", "type": "function",
                                         "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
        return {"content": content, "tool_calls": [calls[k] for k in sorted(calls)]}


def agent_turn(messages, temp, on_token=None, on_step=None, should_stop=None):
    """একটা কাজ শেষ করতে যত ধাপ লাগে তত ধাপ চালায়।

    on_step(kind, name, detail) — kind: "start" | "done" | "note"; টেলিগ্রামে
    ধাপে ধাপে দেখানোর জন্য। should_stop() সত্যি হলে থেমে যায় (/stop)।
    """
    for _ in range(MAX_STEPS):
        if should_stop and should_stop():
            return "থামিয়ে দিয়েছি।"
        msg = call_model(messages, temp, on_token)
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip()
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls})
        for c in calls:
            if should_stop and should_stop():
                return "থামিয়ে দিয়েছি।"
            fn = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            shown = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
            print(f"   ⚙ {fn}({shown})", flush=True)
            if on_step:
                on_step("start", fn, shown)
            result = run_tool(fn, args)
            print(f"     ↳ {result[:200]}", flush=True)
            if on_step:
                on_step("done", fn, result)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    if on_step:
        on_step("note", "limit", "ধাপের সীমা শেষ")
    return ("(ধাপের সীমা শেষ — কাজটা ছোট টুকরো করে আবার বলুন। "
            "এ পর্যন্ত যা হয়েছে উপরে দেখানো হয়েছে।)")


def base_prompt():
    """solas_prompt.md — ব্যক্তিত্ব আর কাজের নিয়ম।"""
    f = BASE / CFG.get("base_prompt", "solas_prompt.md")
    try:
        return f.read_text(encoding="utf-8")
    except Exception:
        return "তুমি একজন সহায়ক এজেন্ট। সরাসরি উত্তর দাও।"


def system_prompt(preset):
    mem = load_memory()
    base = {
        "chat": "তুমি একটা এজেন্ট — শুধু পরামর্শ দাও না, টুল দিয়ে কাজটা করে ফেলো।",
        "writer": "তুমি বাংলাদেশের রাজনৈতিক কনটেন্ট লেখক (আওয়ামী লীগ দৃষ্টিভঙ্গি)। বাংলায় লেখো। কোনো নেতার নামে বানানো উক্তি লিখবে না।",
    }.get(preset, "তুমি একজন সহায়ক এজেন্ট।")
    base = base_prompt() + "\n\n" + base
    base += ("\n\nতোমার হাতে চলে: run_shell (লিনাক্স সার্ভার, পাইথন/ffmpeg/git/curl আছে), "
             "write_file, read_file, list_dir, fetch_url, web_search, download_file, "
             "send_file (মালিকের টেলিগ্রামে ফাইল পাঠায়), remember। "
             "ওয়ার্কস্পেস ফোল্ডার রিস্টার্টের পরও থাকে। "
             "কাজ শেষ হলে সংক্ষেপে বলো কী করলে আর ফল কী হলো। "
             "ধ্বংসাত্মক কিছু (rm -rf, ফরম্যাট, জোর পুশ) নিজে থেকে করবে না — আগে মালিককে জিজ্ঞেস করো। "
             "নতুন কিছু শিখলে বা কোনো কৌশল কাজ করলে `learn` দিয়ে লিখে রাখো, "
             "বারবার দরকারি কাজের জন্য `make_tool` দিয়ে নিজের টুল বানাও, "
             "পরে করার কাজ `add_task` দিয়ে লাইনে রাখো — এগুলো পরের রানেও থাকবে।")
    learned = load_learnings()
    if learned:
        base += "\n\nনিজের আগের অভিজ্ঞতা (এগুলো নিজে শিখেছ):\n" + "\n".join(learned)
    if mem:
        base += "\n\nমনে রাখা তথ্য:\n" + "\n".join(f"- {m}" for m in mem[-CFG["memory_in_prompt"]:])
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="chat")
    ap.add_argument("--temp", type=float, default=0.6)
    a = ap.parse_args()
    messages = [{"role": "system", "content": system_prompt(a.preset)}]
    print("টুলসহ এজেন্ট · /reset · /bye\n")
    while True:
        try:
            q = input("আপনি: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q in ("/bye", "/exit", "bye"):
            break
        if q == "/reset":
            messages = [{"role": "system", "content": system_prompt(a.preset)}]
            print("মেমোরি মুছে ফেলা হলো")
            continue
        if not q:
            continue
        messages.append({"role": "user", "content": q})
        out = agent_turn(messages, a.temp, on_token=lambda p: print(p[-120:], end="\r"))
        messages.append({"role": "assistant", "content": out})
        print("\n\n" + (out or "(কোনো উত্তর আসেনি)") + "\n")


if __name__ == "__main__":
    sys.exit(main())
