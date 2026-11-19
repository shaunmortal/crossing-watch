"""Every v6 holdout prompt (1,545) sent to the served v6 adapter, exactly as the training session sampled it (one user
message, temperature 0, 256 tokens). Saves each reply with its Fireworks response id and usage, cached by index, so a
re-run asks only the missing ones. Stops asking once WALL_CAP_S has passed (the deployment bills per GPU-second).
Run: python3 replay_v6.py accounts/ACCT/deployments/DEP OUT.jsonl
"""
import json
import os
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
TRIES = 4
WALL_CAP_S = 40 * 60
lock = threading.Lock()


def ask(model, content):
    body = {"model": model, "temperature": 0, "max_tokens": 256, "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + os.environ["FIREWORKS_API_KEY"]})
    for attempt in range(TRIES):
        try:
            return json.load(urllib.request.urlopen(req, timeout=300))
        except Exception as e:  # transient 429/5xx/timeouts: back off, then give up on this row
            if attempt == TRIES - 1:
                print(f"failed after {TRIES} tries: {type(e).__name__}: {str(e)[:200]}", flush=True)
                return None
            time.sleep(5 * (attempt + 1))


def main():
    model, out = sys.argv[1], Path(sys.argv[2])
    rows, labels = run.holdout()
    done = {r["index"] for r in map(json.loads, out.read_text().splitlines())} if out.exists() else set()
    start = time.monotonic()

    def one(i):
        if time.monotonic() - start > WALL_CAP_S:
            return
        t = time.monotonic()
        r = ask(model, rows[i]["messages"][0]["content"])
        if r is None:
            return
        line = {"index": i, "id": labels[i]["id"], "response_id": r.get("id"), "model": r.get("model"),
                "reply": r["choices"][0]["message"].get("content") or "", "finish": r["choices"][0].get("finish_reason"),
                "usage": r.get("usage"), "wall_s": round(time.monotonic() - t, 2)}
        with lock, out.open("a") as f:
            f.write(json.dumps(line) + "\n")

    todo = [i for i in range(len(rows)) if i not in done]
    print(f"asking {len(todo)} of {len(rows)}", flush=True)
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, todo))
    got = len(out.read_text().splitlines()) if out.exists() else 0
    print(f"replies saved: {got} of {len(rows)} in {time.monotonic() - start:.0f} s", flush=True)


if __name__ == "__main__":
    main()
