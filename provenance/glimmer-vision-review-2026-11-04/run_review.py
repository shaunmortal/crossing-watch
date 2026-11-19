"""An open-weights model as Crossing Watch's crop reviewer, through the product's own call (review.ask_open, the
REVIEW_MODEL_URL path), on set A (our gate's reviewed crops) and set B (DUT, through validate_offline.py's own scorer).
Every reply is logged with its response id and the product's reading of it; no image data and no account id.
Run from the repo root, with REVIEW_MODEL_URL and REVIEW_MODEL set (REVIEW_TEMPERATURE=0 adds temperature 0):
  python3 run_review.py smoke IMAGE.jpg LOG.jsonl                 one call on a synthetic image, not scored
  python3 run_review.py gate GATE_RUN_DIR LOG.jsonl               the gate run's events.json and person-*.jpg crops
  python3 run_review.py dut LOG.jsonl DUT_REPO RUN... --json SCORES.json    validate_offline.py --reviewer open
PRIVATE_LOG=FILE also keeps each raw reply text there (kept out of the repo).
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import openweights  # noqa: E402
import review  # noqa: E402
import seal  # noqa: E402

TRIES = 3          # transport failures only (no HTTP 200); a reply that arrives is final
RETRY_WAIT_S = 15
TEMPERATURE = os.environ.get("REVIEW_TEMPERATURE")
DROP = [p for p in os.environ.get("REVIEW_DROP_PARAMS", "").split(",") if p]  # params the smoke call showed rejected
current = {"set": "", "item": "", "extra": {}}
original_post, original_ask_open = openweights.post, review.ask_open


def public_model(model):
    """The model id without the deployment path, which names our account."""
    return model.split("#")[0] + (" (on-demand deployment)" if "#" in model else "")


def log(record):
    with open(current["log"], "a") as f:
        f.write(json.dumps(record) + "\n")


def logged_post(url, key, body):
    body = {k: v for k, v in body.items() if k not in DROP}
    if TEMPERATURE is not None:
        body["temperature"] = float(TEMPERATURE)
    started = time.monotonic()
    for attempt in range(1, TRIES + 1):
        try:
            answer = original_post(url, key, body)
            break
        except (urllib.error.HTTPError, OSError) as err:
            code = getattr(err, "code", None)
            print(f"{current['item']}: try {attempt} failed: {code or err}", flush=True)
            if attempt == TRIES or (code is not None and code < 500 and code != 429):
                log({**base(), "error": f"HTTP {code}" if code else type(err).__name__, "tries": attempt,
                     "params": sorted(k for k in body if k != "messages")})
                raise
            time.sleep(RETRY_WAIT_S * attempt)
    text = (answer["choices"][0]["message"].get("content") or "") if answer.get("choices") else ""
    verdict = review.read_verdict(text)
    raw = None
    try:
        raw = json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        pass
    message = (answer.get("choices") or [{}])[0].get("message") or {}
    log({**base(), "response_id": answer.get("id"), "finish_reason": (answer.get("choices") or [{}])[0].get("finish_reason"),
         "usage": answer.get("usage"), "wall_s": round(time.monotonic() - started, 2), "tries": attempt,
         "params": sorted(k for k in body if k != "messages"), "readable": verdict is not None,
         "cyan_is_a_pedestrian": (raw or {}).get("cyan_is_a_pedestrian") if isinstance(raw, dict) else None,
         "road_user": verdict and verdict["road_user"], "is_person": verdict and verdict["is_person"],
         "keep": verdict is not None and (verdict["is_person"] or verdict["road_user"] == "unclear"),
         "reason": review.public_reason(verdict and verdict["reason"], 10**6),  # "" when it holds a digit
         "reply_sha256": hashlib.sha256(text.encode()).hexdigest(),
         "reasoning_chars": len(message.get("reasoning_content") or ""),
         **({} if verdict else {"unreadable_reply": "".join("#" if c.isdigit() else c for c in text[:300])})})
    if os.environ.get("PRIVATE_LOG"):
        with open(os.environ["PRIVATE_LOG"], "a") as f:
            f.write(json.dumps({"item": current["item"], "response_id": answer.get("id"), "reply": text,
                                "reasoning": message.get("reasoning_content")}) + "\n")
    return answer


def base():
    return {"set": current["set"], "item": current["item"], "model": public_model(review.OPEN_MODEL),
            "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **current["extra"]}


def logged_ask_open(image_path, top_down=False):
    path = Path(image_path)
    if current["set"] == "B":
        current["item"] = f"{path.parent.parent.name}/{path.parent.name}/{path.stem.removeprefix('person-')}"
    return original_ask_open(path, top_down)


def gate(run_dir):
    """Set A: every piece Spark reviewed in the gate run, on the very crop Spark saw (checked by its saved hash)."""
    events = json.loads((run_dir / "events.json").read_text())["events"]
    pids = list(dict.fromkeys(e["person"] for e in events if "review" in e))
    for pid in pids:
        crop = run_dir / f"person-{pid.replace('/', '-')}.jpg"
        spark = json.loads(crop.with_suffix(".json").read_text())
        view = next(v for v in (False, True) if seal.inputs_sha256(
            [crop.read_bytes(), review.MODEL, review.PROMPT, review.VIEWS[v]]) == spark["inputs_sha256"])
        said = review.read_verdict(spark["reply"])
        current.update(item=pid, extra={"spark_road_user": said["road_user"],
                                        "spark_keep": said["is_person"] or said["road_user"] == "unclear",
                                        "crop_is_sparks": True, "top_down": view})
        try:
            review.ask_open(crop, view)
        except Exception as err:  # noqa: BLE001 - logged by logged_post; the row then counts as wrong
            print(f"{pid}: {err}", flush=True)
    print(f"set A: {len(pids)} crops asked", flush=True)


def main():
    mode, args = sys.argv[1], sys.argv[2:]
    openweights.post, review.ask_open = logged_post, logged_ask_open
    if not review.OPEN_URL:
        raise SystemExit("set REVIEW_MODEL_URL and REVIEW_MODEL")
    if mode == "smoke":
        current.update(set="smoke", item="synthetic-blank", log=args[1])
        verdict = review.read_verdict(review.ask_open(Path(args[0]), False) or "")
        print("smoke:", verdict and {k: verdict[k] for k in ("is_person", "road_user")}, flush=True)
        if verdict is None:
            raise SystemExit(1)
    elif mode == "gate":
        current.update(set="A", log=args[1])
        gate(Path(args[0]))
    elif mode == "dut":
        import validate_offline
        current.update(set="B", log=args[0])
        sys.argv = ["validate_offline.py", *args[1:], "--reviewer", "open", "--spark", "1000"]
        validate_offline.main()


if __name__ == "__main__":
    main()
