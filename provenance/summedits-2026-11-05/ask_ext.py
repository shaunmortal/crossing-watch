"""Ask one judge about every row of a SummEdits set, with the settings each used in v6: the tuned judge as the served
replay asked it (temperature 0, 256 tokens, no response_format), Muse Spark Open as the product's judge asks it
(json_schema {"problems": [...]}, reasoning_effort low). Cached by index; every reply keeps its Fireworks request id.
Run: python3 ask_ext.py {tuned MODEL_REF | spark-open} SET.jsonl OUT.jsonl"""
import json, os, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
URL = "https://api.fireworks.ai/inference/v1/chat/completions"
SCHEMA = {"type": "object", "properties": {"problems": {"type": "array", "items": {"type": "string"}}}, "required": ["problems"]}
lock = threading.Lock()

def body(judge, model, prompt):
    msg = [{"role": "user", "content": prompt}]
    if judge == "tuned":
        return {"model": model, "messages": msg, "temperature": 0, "max_tokens": 256}
    return {"model": "accounts/fireworks/models/muse-spark-open", "messages": msg, "reasoning_effort": "low",
            "response_format": {"type": "json_schema", "json_schema": {"name": "plan", "schema": SCHEMA}}}

def ask(b):
    req = urllib.request.Request(URL, json.dumps(b).encode(), {"Authorization": "Bearer " + os.environ["FIREWORKS_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=300))
        except Exception as e:
            if attempt == 3:
                print(f"failed: {type(e).__name__}: {str(e)[:160]}", flush=True); return None
            time.sleep(5 * (attempt + 1))

def main():
    judge = sys.argv[1]
    model, set_path, out = (sys.argv[2], sys.argv[3], Path(sys.argv[4])) if judge == "tuned" else (None, sys.argv[2], Path(sys.argv[3]))
    rows = [json.loads(l) for l in open(set_path)]
    done = {json.loads(l)["index"] for l in out.read_text().splitlines()} if out.exists() else set()
    def one(r):
        t = time.monotonic(); a = ask(body(judge, model, r["prompt"]))
        if a is None: return
        line = {"index": r["index"], "id": r["id"], "judge": judge, "request_id": a.get("id"), "model": a.get("model"),
                "reply": a["choices"][0]["message"].get("content") or "", "finish": a["choices"][0].get("finish_reason"),
                "usage": a.get("usage"), "wall_s": round(time.monotonic() - t, 2)}
        with lock, out.open("a") as f: f.write(json.dumps(line) + "\n")
    lo, hi = (int(x) for x in os.environ.get("SLICE", "0,1000000").split(","))  # SLICE=lo,hi: this process's rows
    todo = [r for r in rows if r["index"] not in done and lo <= r["index"] < hi]
    print(f"{judge}: asking {len(todo)} of {len(rows)}", flush=True)
    with ThreadPoolExecutor(16) as pool: list(pool.map(one, todo))
    print(f"{judge}: saved {len(out.read_text().splitlines()) if out.exists() else 0} of {len(rows)}", flush=True)

if __name__ == "__main__":
    main()
