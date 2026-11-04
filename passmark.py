"""G7's after-fix pass mark (GATES.md), which the page shows before any fix exists: a film of the same dismissal after
the fix shows a drop only if a one-sided Fisher exact test at 5% finds both fewer crossings with a moving vehicle
through the same spot within 3 s and fewer distinct such vehicles. Page only: never in pack.facts or the letter."""
import itertools
import math

import road

DROP_P = 0.05  # G7: "drop shown" means one-sided p <= 0.05, the one comparator everywhere
HALVED = 0.5   # the page's power: the chance of passing if the true share of crossings hit halved


def fisher_drop_p(k1, n1, k2, n2):
    """One-sided Fisher exact p: the chance, if nothing changed and both films' totals are fixed, that the after-film
    has k2 or fewer of its n2 with the baseline's k1 of n1."""
    hits = k1 + k2
    return sum(math.comb(n2, j) * math.comb(n1, hits - j) for j in range(k2 + 1)) / math.comb(n1 + n2, hits)


def mark(k1, n1, n2):
    """The largest count of n2 after-film crossings that shows a drop from k1 of n1, or None when not even 0 does."""
    best = None
    for k2 in range(n2 + 1):  # p only grows with k2
        if fisher_drop_p(k1, n1, k2, n2) > DROP_P:
            break
        best = k2
    return best


def chance(k1, n1, n2, ratio=HALVED):
    """The chance an after-film of n2 crossings gets to mark() or fewer if the true share is `ratio` x k1 / n1 (logs,
    so a long film's binomial terms never overflow a float)."""
    top, p = mark(k1, n1, n2), ratio * k1 / n1
    if top is None:
        return 0.0
    return sum(math.exp(math.lgamma(n2 + 1) - math.lgamma(j + 1) - math.lgamma(n2 - j + 1) + j * math.log(p)
                        + (n2 - j) * math.log1p(-p)) for j in range(top + 1))


def counts(events, crossers):
    """G7's (k, V): the `crossers` with a moving vehicle through their spot within road.CLOSE_PASS_S (every event's
    tier), and the distinct vehicles among each one's first such vehicle, by when the person was on the spot. One
    vehicle passing a group counts once in V."""
    first = {}
    for e in sorted(events, key=lambda e: e.get("t_person_s", 0.0)):
        first.setdefault(e["person"].split("/")[0], e["vehicle"])
    hit = {person: vehicle for person, vehicle in first.items() if person in crossers}
    return len(hit), len(set(hit.values()))


def after_mark(events, seen):
    """The page's step after the fix, from the headline's own k and n: the pass mark, its power for one and two
    after-films, or how many after-films a count this low needs. "" without exposure's crosser list."""
    if not seen.get("crossers"):
        return ""
    crossers, tier = set(seen["crossers"]), f"a moving vehicle through the same spot within {road.CLOSE_PASS_S:g} s"
    n, (k, v) = len(crossers), counts(events, crossers)
    if not k:
        return f"None of the {n} crossings had {tier}, so a film after the fix has no count of them to lower."
    test = "one-sided Fisher exact test at 5%, pre-registered as G7 in GATES.md"
    passes = lambda m: mark(k, n, m * n) is not None and mark(v, n, m * n) is not None
    if not passes(1):
        films = next(m for m in itertools.count(2) if passes(m))  # ends: even 1 of n passes at 0 of 19 x n
        return (f"With {k} of the {n} people who crossed having {tier} ({v} distinct vehicle{'' if v == 1 else 's'}), no after-film "
                f"this long can show a drop ({test}): film {films} dismissals after the fix, from the same spot for as "
                "long each.")
    return (f"After the fix, film the same dismissal from the same spot for as long. The drop counts only if "
            f"{mark(k, n, n)} or fewer of about {n} crossings have {tier} (now {k} of {n}) and {mark(v, n, n)} or "
            f"fewer distinct vehicles do (now {v}): a {test}. If the true share halved, one after-film would pass the "
            f"crossings count with {100 * chance(k, n, n):.0f}% chance, and two after-films together "
            f"{100 * chance(k, n, 2 * n):.0f}%. Missing the mark does not show the fix failed.")
