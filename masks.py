"""SAM 3.1's masks: the one_bit mask SAM sends after each box (sam.request asks for it), decoded into the pixels it
covers and found again for a tracked box. For drawing only: every measurement stays on boxes.

The decoder is a port of the one_bit format of Meta's meta-sam-parser (_mask_codec.py, SAM License): base85 text
holding a binary range code, each pixel's odds counted per pattern of its 12 neighbours above and to the left."""
import re
from functools import reduce
from pathlib import Path

MASK = re.compile(r"<\|box;x1=([\d.]+);y1=([\d.]+);x2=([\d.]+);y2=([\d.]+)[^|]*\|>"
                  r"<\|mask;x=0;y=0;data=(\d+),(\d+),!([^|]*)\|>")  # a box, then its mask: height, width, text
TILE = re.compile(r"tile(\d+)_(\d+)")  # analyze.tile_folder: a crop's replies are in its own pixels, offset by x, y
BASE = 85
ALPHABET = "".join(chr(c) for c in range(0x21, 0x7F) if chr(c) not in '"\\,;<>|')[:BASE]  # the digits, in order
DIGIT = {c: i for i, c in enumerate(ALPHABET)}
WORD = 0xFFFFFFFF
TOP, BOTTOM = 1 << 24, 1 << 16  # the range coder moves a byte in when its range falls under these
PAD = 2                         # neighbours are read 2 pixels to each side, so rows are padded with 2 zeros
STEP, LIMIT = 14, 4096          # a bit adds STEP to its pattern's count; at LIMIT the pattern's two counts halve


def key(box):
    """Whole pixels of a box, to match a tracked box with the box SAM sent its mask with."""
    return tuple(round(v) for v in box)


def find(folder, boxes):
    """{key(box): (height, width, text)} for those of `boxes` (whole-clip pixels) that SAM sent a mask with, from
    every cached reply under `folder`: parts, tiles and crowd-mode frames."""
    # ponytail: matched on the box alone, since a part's reply counts frames from the part's start; two boxes agree
    # to the pixel on all four edges only for the same object standing still, whose masks barely differ
    wanted, found = {key(b) for b in boxes}, {}
    for reply in sorted(Path(folder).rglob("*.sam.txt")):
        tile = TILE.fullmatch(reply.parent.name)
        dx, dy = (int(tile[1]), int(tile[2])) if tile else (0, 0)
        for m in MASK.finditer(reply.read_text()):
            k = (round(float(m[1])) + dx, round(float(m[2])) + dy, round(float(m[3])) + dx, round(float(m[4])) + dy)
            if k in wanted:
                found.setdefault(k, (int(m[5]), int(m[6]), m[7]))
    return found


def unpack(text):
    """Base85 text -> bytes: 5 digits of byte count, then 5 digits per 4 bytes; a last group of n bytes has n + 1."""
    digits = [DIGIT[c] for c in text]
    number = lambda group: reduce(lambda total, d: total * BASE + d, group, 0)
    out = bytearray()
    for i in range(5, len(digits), 5):
        group = digits[i:i + 5]
        out += number(group + [BASE - 1] * (5 - len(group))).to_bytes(4, "big")[:len(group) - 1]
    if len(out) != number(digits[:5]):
        raise ValueError("mask text does not hold the byte count it starts with")
    return bytes(out)


def decode(text, height, width):
    """A one_bit mask's text (after its '!') -> `height` rows of `width` bytes, 1 where the object is."""
    try:
        data = unpack(text)
        if len(data) < 4:
            raise ValueError("mask text is too short")
        code, at, low, span = int.from_bytes(data[:4], "big"), 4, 0, WORD
        counts, wide = [1] * (2 << 12), width + 2 * PAD
        seen, rows = bytearray(wide * (height + PAD)), []
        for y in range(height):
            row = bytearray(width)
            for x in range(width):
                p = (y + PAD) * wide + PAD + x
                a, b = p - wide, p - 2 * wide  # the same column one and two rows up
                c = 2 * (seen[p - 1] | seen[p - 2] << 1 | seen[a - 2] << 2 | seen[a - 1] << 3 | seen[a] << 4
                         | seen[a + 1] << 5 | seen[a + 2] << 6 | seen[b - 2] << 7 | seen[b - 1] << 8 | seen[b] << 9
                         | seen[b + 1] << 10 | seen[b + 2] << 11)
                zero, one = counts[c], counts[c + 1]
                scale = span // (zero + one)
                bit = int(min(((code - low) & WORD) // scale, zero + one - 1) >= zero)
                low, span = (low + scale * zero * bit) & WORD, scale * (one if bit else zero)
                while (low ^ (low + span)) & WORD < TOP or span < BOTTOM:
                    if (low ^ (low + span)) & WORD >= TOP:
                        span = -low & (BOTTOM - 1)
                    code, at = (code << 8 | data[at]) & WORD, at + 1
                    low, span = low << 8 & WORD, span << 8 & WORD
                seen[p] = row[x] = bit
                counts[c + bit] += STEP
                if counts[c] + counts[c + 1] >= LIMIT:
                    counts[c], counts[c + 1] = counts[c] >> 1 or 1, counts[c + 1] >> 1 or 1
            rows.append(bytes(row))
        return rows
    except (KeyError, IndexError, OverflowError, ZeroDivisionError) as err:
        raise ValueError(f"not a SAM one_bit mask: {err!r}") from err
