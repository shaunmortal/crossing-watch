"""Tamper-evident hashes: the SHA-256 of the original video (analyze.py) and a standard SHA256SUMS for the shared
folder (pack.py), so a changed clip, picture or page shows. Anyone can check the folder with
`shasum -a 256 -c SHA256SUMS`, or `python3 pack.py --verify FOLDER` (MATCH, CHANGED or MISSING per file)."""
import hashlib
import re
from pathlib import Path

SUMS = "SHA256SUMS"
LINE = re.compile(r"([0-9a-f]{64}) [ *]([^/\\]+)")  # shasum's own format: "<sha256>  <name>", " *" for binary mode


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


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
