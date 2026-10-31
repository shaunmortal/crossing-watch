"""Ask Muse Spark (Meta API, as judge_bench.asker('spark')) and Muse Spark Open (Fireworks, as pack's open judge path)
the 211 v2 holdout judge prompts, one vote each. Every reply is cached (reply, usage, wall s) so a rerun asks only for
rows it lacks. A call that keeps failing for a transient reason is not cached (asked again next run); any other failure
is cached with an empty reply, which read_problems cannot read, so it counts as not flagged.

Run (keys from .env, never printed):
  JUDGE_MODEL_URL=https://api.fireworks.ai/inference/v1 JUDGE_MODEL=accounts/fireworks/models/muse-spark-open \
  python3 run.py {spark|spark-open} [LIMIT]
"""
import hashlib
import http.client
import json
import socket
import sys
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "CROSSING_WATCH")
import pack
import sam
import writers_table

HERE = Path(__file__).parent
HOLDOUT = Path("GLIMMER_FT/cookbook/training/muse_starter_logs/judge-v2-b/holdout.jsonl")
SPLIT = Path("GLIMMER_FT/v2/split.json")
CAP_USD = 4.0          # both judges together
WORST_CALL_USD = 0.03  # held back per call in flight, and charged for a failure with no usage
TRIES = 4
WORKERS = 4
PRICE = writers_table.PRICES["muse-spark-1.3"]  # same list price as Spark Open (1.25 / 0.15 / 4.25 per 1M)
TRANSIENT = (urllib.error.URLError, http.client.HTTPException, socket.timeout, TimeoutError, ConnectionError)
lock = threading.Lock()


def usd(row):
    prompt, cached, completion, _ = writers_table.tokens(row.get("usage"))
    if prompt is None or completion is None:
        return WORST_CALL_USD
    cached = cached or 0
    return ((prompt - cached) * PRICE[0] + cached * PRICE[1] + completion * PRICE[2]) / writers_table.PER


def load(path):
    return [json.loads(line) for line in path.open()] if path.is_file() else []


def spent():
    return sum(usd(r) for name in ("spark", "spark-open") for r in load(HERE / f"{name}.jsonl"))


def asker(judge):
    if judge == "spark":
        key = sam.load_api_key()
        return lambda prompt: pack.spark_run(prompt, None, key)
    if not pack.JUDGE_URL:
        raise SystemExit("spark-open needs JUDGE_MODEL_URL and JUDGE_MODEL")
    return lambda prompt: pack.open_model_reply(prompt, None, pack.PROBLEMS_SCHEMA, judge=True)


def transient(err):
    if isinstance(err, urllib.error.HTTPError):
        return err.code == 429 or err.code >= 500
    return isinstance(err, TRANSIENT)


def ask(call, prompt):
    """(text, record) or None after TRIES transient failures; a non-transient failure gives ("", {"error": ...})."""
    for attempt in range(TRIES):
        try:
            return call(prompt)
        except Exception as err:  # classified below: transient retried, anything else cached as unreadable
            if not transient(err):
                return "", {"error": f"{type(err).__name__}: {str(err)[:200]}"}
            print(f"transient ({type(err).__name__}: {str(err)[:120]}), try {attempt + 1}/{TRIES}", file=sys.stderr)
            time.sleep(5 * 2 ** attempt)
    return None


def main():
    judge, limit = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None
    out = HERE / f"{judge}.jsonl"
    prompts = [json.loads(line)["messages"][0]["content"] for line in HOLDOUT.open()]
    labels = json.load(SPLIT.open())["holdout"]
    assert len(prompts) == len(labels) == 211
    done = {r["index"] for r in load(out)}
    todo = [i for i in range(len(prompts)) if i not in done][:limit]
    call, state = asker(judge), {"spent": spent(), "in_flight": 0}

    def one(i):
        with lock:
            if state["spent"] + (state["in_flight"] + 1) * WORST_CALL_USD > CAP_USD:
                print(f"row {i}: skipped, ${state['spent']:.2f} spent, cap ${CAP_USD}", file=sys.stderr)
                return
            state["in_flight"] += 1
        got = ask(call, prompts[i])
        with lock:
            state["in_flight"] -= 1
            if got is None:
                print(f"row {i}: still failing, asked again next run", file=sys.stderr)
                return
            text, record = got
            row = {"index": i, "id": labels[i]["id"], "set": labels[i]["set"],
                   "prompt_sha256": hashlib.sha256(prompts[i].encode()).hexdigest(), "reply": text,
                   **{k: record.get(k) for k in ("usage", "wall_s", "request_id", "response_format", "error")
                      if record.get(k) is not None}}
            state["spent"] += usd(row)
            with out.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, todo))
    rows = load(out)
    print(f"{judge}: {len(rows)}/211 cached, ${sum(map(usd, rows)):.4f} for this judge, ${spent():.4f} both")


if __name__ == "__main__":
    main()
