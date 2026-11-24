"""Ranking. Relevance comes from `relevance` when a viewer scored it, else from title words. Unknown values score a neutral 0.5."""
import re
TRUST = dict(A=1.0, B=0.6, C=0.3)


def _words(s): return set(re.findall(r"\w+", s.lower()))


def rank(cands, shot, brief, sources):
    want = _words(" ".join([shot["description"], *shot["queries"]]))
    raw = [len(want & _words(c["title"])) / max(1, len(want)) for c in cands]
    seen_any = any("relevance" in c for c in cands)
    lo, hi = min(raw, default=0), max(raw, default=0)
    base = []
    for c, r in zip(cands, raw):
        rel = (r - lo) / (hi - lo) if hi > lo else (1.0 if hi else 0.0)
        if seen_any:        # a viewed candidate is never compared with a title-word guess
            rel = c.get("relevance", 0.5)
        m = c.get("media")
        dur = min(1.0, m["duration_s"] / shot["duration_s"]) if m else 0.5
        res = min(1.0, min(m["width"], m["height"]) / 1080) if m else 0.5
        o = ("square" if m["width"] == m["height"] else "landscape" if m["width"] > m["height"] else "portrait") if m else None
        ori = 0.5 if o is None else float(o == brief["orientation"])
        tech = 0.20 * dur + 0.15 * res + 0.10 * ori + 0.10 * TRUST[sources[c["source_id"]]["source_trust"]]
        # once someone has looked, what is in the picture outweighs missing metadata; before that, title words are a weak hint
        base.append(0.65 * rel + tech * 0.25 / 0.55 if seen_any else 0.35 * rel + tech)
    left, seen, out = list(range(len(cands))), {}, []
    while left:
        f = lambda i: base[i] + 0.10 / (1 + seen.get(cands[i]["source_id"], 0))
        b = max(left, key=lambda i: (f(i), [-ord(x) for x in cands[i]["asset_id"]]))
        left.remove(b)
        out.append(dict(cands[b], score=round(min(1.0, f(b)), 4), scorer=cands[b].get("scorer", "none") if "relevance" in cands[b] else "none"))
        seen[cands[b]["source_id"]] = seen.get(cands[b]["source_id"], 0) + 1
    return out
