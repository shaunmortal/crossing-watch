"""Base Muse Glimmer 30B (no LoRA) on the v6 holdout prompts, the fair way: the same single user message the training
session sampled, temperature 0, a long reply cap so its reasoning can finish, and JSON mode so a finished verdict is
readable. Rows are asked in a seeded shuffle and the run stops at WALL_CAP_S, so the rows with a reply are a random
sample of the holdout (the pre-registration in GATES.md says how they are scored).
Run: python3 replay_base.py MODEL OUT.jsonl MAX_TOKENS WALL_CAP_S
"""
import json
import os
import random
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "v6" / "labels"))
import run  # noqa: E402  (v6 label protocol: holdout() replays the starter's shuffle and checks the sha256)

URL = "https://api.fireworks.ai/inference/v1/chat/completions"
WORKERS = 16
TRIES = 3
SEED = 20261104
lock = threading.Lock()


def ask(model, content, max_tokens):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Authorization": "Bearer " + os.environ["FIREWORKS_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(TRIES):
        try:
            return json.load(urllib.request.urlopen(req, timeout=900))
        except Exception as e:
            if attempt == TRIES - 1:
                print(f"failed after {TRIES} tries: {type(e).__name__}: {str(e)[:200]}", flush=True)
                return None
            time.sleep(10 * (attempt + 1))


def main():
    model, out, max_tokens, wall_cap = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4])
    rows, labels = run.holdout()
    done = {r["index"] for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    start = time.monotonic()

    def one(i):
        if time.monotonic() - start > wall_cap:
            return
        t = time.monotonic()
        r = ask(model, rows[i]["messages"][0]["content"], max_tokens)
        if r is None:
            return
        msg = r["choices"][0]["message"]
        line = {"index": i, "id": labels[i]["id"], "response_id": r.get("id"), "model": r.get("model"),
                "reply": msg.get("content") or "", "reasoning_chars": len(msg.get("reasoning_content") or ""),
                "finish": r["choices"][0].get("finish_reason"), "usage": r.get("usage"),
                "wall_s": round(time.monotonic() - t, 2)}
        with lock, out.open("a") as f:
            f.write(json.dumps(line) + "\n")

    todo = [i for i in range(len(rows)) if i not in done]
    random.Random(SEED).shuffle(todo)
    print(f"asking up to {len(todo)} of {len(rows)} (cap {max_tokens} tokens, wall {wall_cap:.0f} s)", flush=True)
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, todo))
    got = len(out.read_text().splitlines()) if out.exists() else 0
    print(f"replies saved: {got} of {len(rows)} in {time.monotonic() - start:.0f} s", flush=True)


if __name__ == "__main__":
    main()
