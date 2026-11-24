"""RFC 9309 matcher: merged groups, longest match, Allow wins ties, `*` and `$`. Stdlib's parser lacks wildcards."""
import re
from urllib.parse import quote, urlsplit

TOKEN, CAP = "footage-scout", 500 << 10


def _norm(p):
    p = quote(p, safe="/%?=&:;@!$'()*+,~#[]-._")
    f = lambda m: (c if (c := chr(int(m[1], 16))) in "-._~" or c.isascii() and c.isalnum() else m[0].upper())
    return re.sub(r"%([0-9A-Fa-f]{2})", f, p)


def parse(txt):
    groups, cur, open_ = {}, [], False
    for line in txt.lstrip("﻿").splitlines():
        k, sep, v = line.split("#", 1)[0].partition(":")
        k, v = k.strip().lower(), v.strip()
        if not sep:
            continue
        if k == "user-agent":
            if not open_:
                cur = []
            name = v.lower() if v == "*" else (re.match(r"[a-z_-]*", v.lower()) or [""])[0]
            cur.append(name)
            groups.setdefault(name, dict(rules=[], delay=0.0))
            open_ = True
        elif k in ("allow", "disallow"):
            open_ = False
            if v:
                for n in cur:
                    groups[n]["rules"].append((k == "allow", _norm(v)))
        elif k == "crawl-delay":
            open_ = False
            for n in cur:
                if re.fullmatch(r"\d{1,6}(\.\d+)?", v):
                    groups[n]["delay"] = max(groups[n]["delay"], float(v))
    return groups.get(TOKEN) or groups.get("*") or dict(rules=[], delay=0.0)


def _match(pat, path):
    """Linear wildcard match (no regex backtracking on hostile rules)."""
    end = pat.endswith("$")
    parts = (pat[:-1] if end else pat).split("*")
    if not path.startswith(parts[0]):
        return False
    i = len(parts[0])
    if len(parts) == 1:
        return not end or i == len(path)
    for x in parts[1:-1]:
        j = path.find(x, i)
        if j < 0:
            return False
        i = j + len(x)
    last = parts[-1]
    return (path.endswith(last) and len(path) - len(last) >= i) if end else path.find(last, i) >= 0


def allowed(group, url):
    u = urlsplit(url)
    path = _norm((u.path or "/") + ("?" + u.query if u.query else ""))
    if path == "/robots.txt":
        return True
    best = (-1, True)
    for ok, pat in group["rules"]:
        if _match(pat, path):
            best = max(best, (len(pat), ok))
    return best[1]
