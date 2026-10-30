"""Open-weights servers for the letter and its judge: any OpenAI-compatible chat server, e.g. llama-server running
Muse Glimmer 30B on Kaggle, or Muse Spark Open on Fireworks (a hackathon infra partner). The product name behind an
API model id, where it ran, the key it takes, and one measured reply."""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import sam

NAMES = {"accounts/fireworks/models/muse-spark-open": "Muse Spark Open"}  # API model id -> product name
FIREWORKS_HOST = "api.fireworks.ai"  # Fireworks' serverless API: the page says "on Fireworks"
FIREWORKS_KEY = "FIREWORKS_API_KEY"  # its key, from the environment or .env when none is set for that server
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")  # a server here runs on the machine that ran pack.py
TIMEOUT_S = 900  # a 30B model on two T4s writes a letter in minutes, not seconds
REJECTED = 400  # HTTP status of a server that will not hold its reply to the json_schema format


def name(model):
    """The product name for an API model id; any other id (llama-server takes any) is its own name."""
    return NAMES.get(model, model)


def host(url):
    return urllib.parse.urlsplit(url).hostname


def provider(url):
    """The inference provider that runs `url`, as the page names it, or ""."""
    return "Fireworks" if host(url) == FIREWORKS_HOST else ""


def label(url, model):
    """Who runs at `url`: "self-hosted" only when the server is this machine, "on Fireworks" on Fireworks' API, and
    nothing for any other URL, which could be anyone's."""
    where = ", self-hosted" if host(url) in LOCAL_HOSTS else f", on {provider(url)}" if provider(url) else ""
    return f"{name(model)} (open weights{where})"


def server_key(url, key):
    """`key`, the one set for this server, or on Fireworks' API with none set, FIREWORKS_API_KEY: a key never goes to
    another server."""
    return key or (sam.env_value(FIREWORKS_KEY) if host(url) == FIREWORKS_HOST else "")


def reply(url, model, key, content, schema, effort=None):
    """One chat completion held to `schema`: the text, and its run record (llama-server's own timings, the usage, the
    request id, the wall seconds measured here from the first request, and the response_format that was answered).
    A server that rejects json_schema (HTTP 400) is asked once more for any JSON object; the code check and the
    judges stay the backstop. `effort` (reasoning_effort) is sent to Fireworks' API only: llama-server was not
    measured with it."""
    ask = {"model": model, "messages": [{"role": "user", "content": content}],
           **({"reasoning_effort": effort} if effort and host(url) == FIREWORKS_HOST else {})}
    started = time.monotonic()
    try:
        answer, used = post(url, key, {**ask, "response_format": {
            "type": "json_schema", "json_schema": {"name": "plan", "schema": schema}}}), "json_schema"
    except urllib.error.HTTPError as err:
        if err.code != REJECTED:
            raise
        print(f"{name(model)} rejected json_schema ({err.read()[:200].decode(errors='replace')}): asking for any JSON "
              "object", file=sys.stderr)
        answer, used = post(url, key, {**ask, "response_format": {"type": "json_object"}}), "json_object"
    wall_s = round(time.monotonic() - started, 1)
    choice, tokens = answer["choices"][0], (answer.get("usage") or {}).get("completion_tokens", "?")
    print(f"open model reply: finish_reason {choice.get('finish_reason')}, {tokens} tokens",  # the Kaggle notebook
          file=sys.stderr)                                                                     # counts these as tries
    if choice.get("finish_reason") == "length":  # llama-server's only sign: HTTP 200 and an empty answer
        raise ValueError(f"{name(model)} ran out of context after {tokens} tokens with no answer: start llama-server "
                         "with a larger -c or a lower reasoning_strength")
    return choice["message"]["content"], {"timings": answer.get("timings"), "usage": answer.get("usage"),
                                          "request_id": answer.get("id"), "wall_s": wall_s, "response_format": used}


def post(url, key, body):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as response:
        return json.load(response)
