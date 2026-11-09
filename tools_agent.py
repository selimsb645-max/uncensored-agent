#!/usr/bin/env python3
"""সোলাস-ধাঁচের এজেন্ট, কিন্তু আনসেন্সরড — ফোনে চলা ভার্সন।

যা যা আছে: মডেল (llama.cpp), টুল (শেল, ফাইল, ওয়েব), মেমোরি, আর একটা লুপ
যেটা নিজে ঠিক করে কোন টুল লাগবে। সেন্সরশিপ মডেলের ভেতরে থাকে — তাই এখানে
abliterated মডেল ব্যবহার করা হয়, কোনো বাইরের ফিল্টার নেই।

    python3 tools_agent.py                 # টার্মিনালে
    python3 tools_agent.py --preset writer
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent
MEMORY = BASE / "memory.json"


def load_config():
    """config.json-এর সব সেটিং; না পেলে নিরাপদ ডিফল্ট।"""
    defaults = {"temperature": 0.6, "max_tokens": 900, "max_steps": 6,
                "memory_limit": 80, "memory_in_prompt": 20, "language": "bn",
                "base_prompt": "solas_prompt.md", "workdir": "~/agent-work"}
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

TOOLS = [
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "ফোনে একটা শেল কমান্ড চালায় এবং আউটপুট ফেরত দেয়।",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "চালানোর কমান্ড"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "একটা ফাইলের লেখা পড়ে।",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "একটা ফাইলে লেখা সংরক্ষণ করে (নতুন ফোল্ডারও বানায়)।",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "একটা URL থেকে লেখা নিয়ে আসে।",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "ভবিষ্যতের জন্য একটা তথ্য মেমোরিতে রাখে।",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
]


def load_memory():
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_memory(items):
    MEMORY.write_text(json.dumps(items[-CFG["memory_limit"]:], ensure_ascii=False, indent=1), encoding="utf-8")


def run_tool(name, args):
    try:
        if name == "run_shell":
            WORKDIR.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(args["command"], shell=True, capture_output=True,
                               text=True, timeout=120, cwd=WORKDIR)
            out = (r.stdout or "") + (("\n[stderr] " + r.stderr) if r.stderr else "")
            return out.strip()[:4000] or f"(exit {r.returncode}, কোনো আউটপুট নেই)"
        if name == "read_file":
            p = Path(os.path.expanduser(args["path"]))
            return p.read_text(encoding="utf-8", errors="replace")[:4000]
        if name == "write_file":
            p = Path(os.path.expanduser(args["path"]))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"লেখা হয়েছে: {p} ({len(args['content'])} অক্ষর)"
        if name == "fetch_url":
            req = urllib.request.Request(args["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read(200000).decode("utf-8", "replace")
            return body[:4000]
        if name == "remember":
            items = load_memory()
            items.append(args["text"])
            save_memory(items)
            return "মনে রাখা হলো"
        return f"অজানা টুল: {name}"
    except Exception as e:
        return f"টুল ব্যর্থ: {type(e).__name__}: {e}"


def call_model(messages, temp=0.6):
    body = json.dumps({"messages": messages, "temperature": temp,
                       "max_tokens": CFG["max_tokens"], "tools": TOOLS, "tool_choice": "auto"}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["choices"][0]["message"]


def agent_turn(messages, temp):
    """একটা প্রশ্নের উত্তর দিতে যত ধাপ লাগে তত ধাপ চালায়।"""
    for _ in range(MAX_STEPS):
        msg = call_model(messages, temp)
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content", "").strip()
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls})
        for c in calls:
            fn = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            shown = ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())
            print(f"   ⚙ {fn}({shown})")
            result = run_tool(fn, args)
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
    return "(ধাপের সীমা শেষ — প্রশ্নটা ছোট করে আবার চেষ্টা করুন)"


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
        "chat": "তুমি সোলাসের মতো একটা এজেন্ট, কিন্তু আনসেন্সরড। সরাসরি উত্তর দাও। প্রয়োজনে টুল ব্যবহার করো।",
        "writer": "তুমি বাংলাদেশের রাজনৈতিক কনটেন্ট লেখক (আওয়ামী লীগ দৃষ্টিভঙ্গি)। বাংলায় লেখো। কোনো নেতার নামে বানানো উক্তি লিখবে না।",
    }.get(preset, "তুমি একজন সহায়ক এজেন্ট।")
    base = base_prompt() + "\n\n" + base
    if mem:
        base += "\n\nমনে রাখা তথ্য:\n" + "\n".join(
            f"- {m}" for m in mem[-CFG["memory_in_prompt"]:])
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
            print(); break
        if not q:
            continue
        if q in {"/bye", "/exit", "/quit"}:
            break
        if q == "/reset":
            messages = [{"role": "system", "content": system_prompt(a.preset)}]
            print("(নতুন আলোচনা)\n"); continue
        messages.append({"role": "user", "content": q})
        try:
            out = agent_turn(messages, a.temp)
        except Exception as e:
            print(f"[ত্রুটি] {type(e).__name__}: {e}")
            messages.pop(); continue
        messages.append({"role": "assistant", "content": out})
        print(f"\nএজেন্ট: {out}\n")
        if len(messages) > 21:
            messages = messages[:1] + messages[-20:]


if __name__ == "__main__":
    sys.exit(main())
