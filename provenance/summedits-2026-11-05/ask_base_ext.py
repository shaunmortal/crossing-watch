"""Base Muse Glimmer 30B (no LoRA) on the SummEdits replication rows, two arms as pre-registered in GATES.md:
'cap256' exactly as the tuned judge was asked (temperature 0, 256 tokens, no response_format), and 'cap8192'
(temperature 0, 8,192 tokens, JSON mode), asked in a seeded shuffle until WALL_S has passed; every answered row is
scored. Cached by index; every reply keeps its Fireworks request id.
Run: python3 ask_base_ext.py MODEL_REF {cap256|cap8192} SET.jsonl OUT.jsonl WALL_S"""
import json, os, random, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
URL = "https://api.fireworks.ai/inference/v1/chat/completions"
lock = threading.Lock()

def body(model, arm, prompt):
    b = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    return {**b, "max_tokens": 256} if arm == "cap256" else {**b, "max_tokens": 8192, "response_format": {"type": "json_object"}}

def ask(b):
    req = urllib.request.Request(URL, json.dumps(b).encode(), {"Authorization": "Bearer " + os.environ["FIREWORKS_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=900))
        except Exception as e:
            if attempt == 2:
                print(f"failed: {type(e).__name__}: {str(e)[:160]}", flush=True); return None
            time.sleep(10 * (attempt + 1))

def main():
    model, arm, set_path, out, wall = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), float(sys.argv[5])
    rows = [json.loads(l) for l in open(set_path)]
    done = {json.loads(l)["index"] for l in out.read_text().splitlines()} if out.exists() else set()
    start = time.monotonic()
    def one(r):
        if time.monotonic() - start > wall: return
        t = time.monotonic(); a = ask(body(model, arm, r["prompt"]))
        if a is None: return
        m = a["choices"][0]["message"]
        line = {"index": r["index"], "id": r["id"], "judge": f"base-{arm}", "request_id": a.get("id"), "model": a.get("model"),
                "reply": m.get("content") or "", "reasoning_chars": len(m.get("reasoning_content") or ""),
                "finish": a["choices"][0].get("finish_reason"), "usage": a.get("usage"), "wall_s": round(time.monotonic() - t, 2)}
        with lock, out.open("a") as f: f.write(json.dumps(line) + "\n")
    todo = [r for r in rows if r["index"] not in done]
    random.Random(20261107).shuffle(todo)
    print(f"base {arm}: asking up to {len(todo)} of {len(rows)} (wall {wall:.0f} s)", flush=True)
    with ThreadPoolExecutor(32) as pool: list(pool.map(one, todo))
    print(f"base {arm}: saved {len(out.read_text().splitlines()) if out.exists() else 0} of {len(rows)} in {time.monotonic() - start:.0f} s", flush=True)

if __name__ == "__main__":
    main()
