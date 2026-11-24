"""Weekly source health. Results may only lower a source's status (active -> degraded -> retired); nothing here loosens the gate."""
import datetime as dt, hashlib, html, re

RETIRE_AFTER = 4


def week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def step(old, ok, error, terms, today):
    """One source, one run. Re-running in the same week replaces that week's result instead of counting twice."""
    w = week(today)
    n = old.get("failures", 0) if old else 0
    if old and old.get("week") == w:
        n = old.get("before", 0)
    d = dict(week=w, before=n, failures=0 if ok else n + 1, last_ok=today.isoformat() if ok else (old or {}).get("last_ok"),
             error=None if ok else str(error)[:300], terms_sha256=terms or (old or {}).get("terms_sha256"))
    return d


def status(base, h):
    if base != "active" or not h or not h["failures"]:
        return base
    return "retired" if h["failures"] >= RETIRE_AFTER else "degraded"


def overlay(sources, health):
    """Apply a validated health file to the source table."""
    for i, h in health["sources"].items():
        if i in sources:
            sources[i] = dict(sources[i], status=status(sources[i]["status"], h))
    return sources


def terms_hash(page):
    t = re.sub(r"<(script|style|noscript)\b.*?</\1>|<!--.*?-->|<[^>]+>", " ", page, flags=re.S | re.I)
    t = re.sub(r"\s+", " ", html.unescape(t)).strip().casefold()
    return hashlib.sha256(t.encode()).hexdigest()
