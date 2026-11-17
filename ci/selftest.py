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
    return 0 if used_tool else 2


if __name__ == "__main__":
    sys.exit(main())
