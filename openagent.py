"""The case agent's turns on an open-weights model behind an OpenAI-compatible /chat/completions, e.g. Muse Spark Open
on Fireworks. AGENT_MODEL_URL names the server (unset: agent.py talks to Muse Spark on the Meta API, as before),
AGENT_MODEL its API model id, AGENT_MODEL_KEY its key (on Fireworks' API, FIREWORKS_API_KEY when none is set: a key
never goes to another server). The same tools, one per turn; the dollar cap at the price writers_table.py quotes."""
import json
import urllib.error

import openweights
import sam
import writers_table

URL = sam.env_value("AGENT_MODEL_URL")
MODEL = sam.env_value("AGENT_MODEL") or "accounts/fireworks/models/muse-spark-open"
KEY = sam.env_value("AGENT_MODEL_KEY")


def label():
    """Who runs the turns, as the page and the log say it: "Muse Spark Open (open weights, on Fireworks)"."""
    return openweights.label(URL, MODEL)


def quote():
    """writers_table's quoted price for MODEL: (input, cached input, output USD per 1M tokens, source page)."""
    if MODEL not in writers_table.PRICES:
        raise SystemExit(f"writers_table.PRICES quotes no price for {MODEL}: the agent's dollar cap needs one")
    return writers_table.PRICES[MODEL]


def price_words():
    usd_in, cached, usd_out, source = quote()
    where = openweights.provider(URL) or openweights.host(URL)
    return (f"{where} list price for {MODEL} (${usd_in:g} / ${usd_out:g} per 1M tokens, ${cached:g} cached input; "
            f"read {writers_table.PRICES_READ} from {source})")


def chat_tools(tools):
    """agent.TOOLS (Responses API function tools) as Chat Completions tools."""
    return [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}} for t in tools]


def step(instructions, messages, tools):
    """One turn: (the first tool call as {"call_id", "name", "arguments"} or None, the usage, the tool_choice the
    server answered). The reply's reasoning_content is not replayed, as Spark's reasoning items are not. A reply
    without a message is a ValueError, an HTTP error an OSError: the case pauses."""
    body = {"model": MODEL, "messages": [{"role": "system", "content": instructions}, *messages],
            "tools": chat_tools(tools), "parallel_tool_calls": False}
    reply, choice = ask(body)
    try:
        message = reply["choices"][0]["message"]
        calls = message.get("tool_calls") or []
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ValueError(f"the model's reply holds no message: {str(reply)[:200]}") from None
    return first_call(calls, len(messages)), reply.get("usage") or {}, choice


def ask(body):
    """The reply and its tool_choice: "required", so every turn calls a tool (Fireworks: "Model must call at least one
    tool", https://docs.fireworks.ai/guides/function-calling), or "auto" from a server that rejects that with HTTP 400."""
    # ponytail: "required" is tried every turn (a 400 bills no tokens); keep the fallback per case if 400s get slow
    key = openweights.server_key(URL, KEY)
    try:
        return openweights.post(URL, key, {**body, "tool_choice": "required"}), "required"
    except urllib.error.HTTPError as err:
        if err.code != openweights.REJECTED:
            raise
    return openweights.post(URL, key, {**body, "tool_choice": "auto"}), "auto"


def first_call(calls, n):
    """The first well-formed tool call; one with no function name counts as plain text. Its arguments stay as sent,
    so agent.run_tool reports bad JSON or an unknown tool back to the model."""
    call = calls[0] if isinstance(calls, list) and calls and isinstance(calls[0], dict) else {}
    function = call.get("function")
    if not (isinstance(function, dict) and isinstance(function.get("name"), str)):
        return None
    return {"call_id": call.get("id") or f"call-{n}", "name": function["name"], "arguments": function.get("arguments")}


def replay(call, result):
    """The call and its result for the next turn's messages. Arguments that are no JSON object are replayed as "{}"
    (a server that re-reads them could reject the whole history); the result already quotes what was sent."""
    arguments = call["arguments"] if isinstance(call["arguments"], str) else json.dumps(call["arguments"])
    try:
        sent = arguments if isinstance(json.loads(arguments), dict) else "{}"
    except ValueError:
        sent = "{}"
    return [{"role": "assistant", "content": None, "tool_calls": [
                {"id": call["call_id"], "type": "function", "function": {"name": call["name"], "arguments": sent}}]},
            {"role": "tool", "tool_call_id": call["call_id"], "content": json.dumps(result)}]
