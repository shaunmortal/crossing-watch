"""Tamper-evident hashes: the SHA-256 of the original video (analyze.py) and a standard SHA256SUMS for the shared
folder (pack.py), so a changed clip, picture or page shows. Anyone can check the folder with
`shasum -a 256 -c SHA256SUMS`, or `python3 pack.py --verify FOLDER` (MATCH, CHANGED or MISSING per file).
Also reused(): Spark's and Wonder's replies kept by the SHA-256 of what was sent, so same footage, same numbers."""
import hashlib
import json
import re
from pathlib import Path

SUMS = "SHA256SUMS"
LINE = re.compile(r"([0-9a-f]{64}) [ *]([^/\\]+)")  # shasum's own format: "<sha256>  <name>", " *" for binary mode


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def inputs_sha256(inputs):
    """One SHA-256 for a list of bytes or texts, each hashed on its own: [b"ab", b"c"] and [b"a", b"bc"] differ."""
    each = [hashlib.sha256(i if isinstance(i, bytes) else i.encode()).hexdigest() for i in inputs]
    return hashlib.sha256(json.dumps(each).encode()).hexdigest()


def reused(path, inputs, ask, read):
    """read(reply) for the raw reply text saved at `path` while its `inputs` are unchanged, else for a new ask() (the
    reply text, or None when the call failed). Only a reply that read() accepts is saved, so a failed call or an
    unreadable reply is asked again next run, and a later fix to read() applies to every saved reply."""
    key = inputs_sha256(inputs)
    try:
        saved = json.loads(Path(path).read_text())
    except (OSError, ValueError):  # none yet, or cut short: ask again
        saved = None
    if isinstance(saved, dict) and saved.get("inputs_sha256") == key and isinstance(saved.get("reply"), str) \
            and (answer := read(saved["reply"])) is not None:
        return answer
    reply = ask()
    answer = None if reply is None else read(reply)
    if answer is not None:
        Path(path).write_text(json.dumps({"inputs_sha256": key, "reply": reply}))
    return answer


def write_sums(folder):
    """folder/SHA256SUMS for every other file in it, written last, so it covers the page too."""
    names = sorted(p.name for p in Path(folder).iterdir() if p.is_file() and p.name != SUMS)
    (Path(folder) / SUMS).write_text("".join(f"{file_sha256(Path(folder) / name)}  {name}\n" for name in names))


def verify(folder):
    """{name: "MATCH", "CHANGED" or "MISSING"} for every file folder/SHA256SUMS lists. A line that is not
    "<sha256>  <name>" for a file in the folder itself is refused, not skipped."""
    status = {}
    for number, line in enumerate((Path(folder) / SUMS).read_text().splitlines(), 1):
        match = LINE.fullmatch(line)
        if not match or match[2] in (".", ".."):
            raise ValueError(f"{SUMS} line {number} is not '<sha256>  <file name>': {line[:80]!r}")
        path = Path(folder) / match[2]
        status[match[2]] = ("MISSING" if not path.is_file() else
                            "MATCH" if file_sha256(path) == match[1] else "CHANGED")
    return status
