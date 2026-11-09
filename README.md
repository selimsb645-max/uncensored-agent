# আনসেন্সরড এজেন্ট (ফোনে, অফলাইন)

নিজের ফোনে চলা একটা চ্যাট এজেন্ট। মডেল ফোনেই চলে, ইন্টারনেট লাগে না,
কোনো ক্লাউড ফিল্টার নেই।

## একবার সেটআপ (Termux)

```bash
pkg install -y git
git clone <এই-রেপোর-লিংক> ~/uncensored-agent
cd ~/uncensored-agent && bash setup.sh
```

`setup.sh` যা করে: প্যাকেজ ইনস্টল → llama.cpp বিল্ড → Qwen2.5-3B-Instruct-abliterated
(Q4_K_M, ~২ GB) ডাউনলোড।

## চালানো

```bash
bash ~/uncensored-agent/start.sh
```

প্রথমবার মডেল লোড হতে ৩০-৬০ সেকেন্ড। এরপর `আপনি:` প্রম্পটে লিখুন।
বের হতে `/bye`, নতুন আলোচনার জন্য `/reset`।

## নিজের মতো সাজানো

```bash
python3 agent.py --system "তুমি একজন রাজনৈতিক কনটেন্ট লেখক, বাংলায় লেখো" --temp 0.9
```

## ফোনে টিপস

- ৪ GB RAM থাকলে মডেলটা আরামে চলবে; ৩ GB-তে `-c 2048` করে নিন (start.sh-এ)।
- `termux-wake-lock` দেওয়া আছে, তবু Termux-কে Battery → Unrestricted রাখুন।
- মডেল বদলাতে চাইলে `~/models/`-এ নতুন GGUF রাখুন আর start.sh-এ নাম বদলান।

## অন্য মডেল (যদি আরও শক্তিশালী চান)

| মডেল | সাইজ | ফোনে গতি |
|---|---|---|
| Qwen2.5-3B-Instruct-abliterated Q4_K_M | ~২ GB | দ্রুত |
| Dolphin3.0-Qwen2.5-3B Q4_K_M | ~২ GB | দ্রুত |
| Qwen2.5-7B-Instruct-abliterated Q4_K_M | ~৪.৫ GB | ধীর (৬-৮ GB RAM দরকার) |

## কেন GitHub Actions-এ নয়

Actions-এ GPU নেই, জব ৬ ঘণ্টায় শেষ হয়, ডিস্ক ইফেমেরাল — মডেল ২৪/৭ চালানো যায় না।
তাই কোড GitHub-এ, রান ফোনে।
