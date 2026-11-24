"""Weekly live smoke test: one search and one resolve per automatic source. Downloads nothing.
usage: python scripts/smoke.py [--write] [--only ID] -o OUT_DIR     exit 0: all ok, 1: something changed or failed"""
import argparse, datetime as dt, json, pathlib, re, sys, time
from urllib.parse import urlsplit
from footage_scout import gate, health, providers
from footage_scout.core import FscError, load_sources, read_json, validate, write_json
from footage_scout.http import Http

ROOT = pathlib.Path(__file__).resolve().parents[1]
Q = dict(nasa_images="aurora", nasa_svs="moon", commons="forest", ia="cattle", ia_nasa="apollo", loc="train", openbeelden="school", esahubble="nebula", esawebb="galaxy",
         eso="telescope", noirlab="nebula", isorepublic="forest", dareful="forest", nps="bison", usgs="volcano", nasa_eol="aurora", netflix_open="film")

# no contact configured, or the shared runner address is rate-limited: says nothing about the source
SKIP = re.compile(r"set FSC_CONTACT_URL|asked us to wait|: HTTP 429$")


def probe(http, src):
    ad = providers.get(http, src)
    ids = ad.search(Q[src["id"]], 3)
    if not ids:
        raise FscError("search returned nothing")
    last, c = None, None
    for i in ids:     # single items disappear or have no file; the adapter is broken only when every one of them fails
        try:
            c = ad.resolve(i)
        except FscError as e:
            last = e
            continue
        if c["file_url"]:
            break
    if c is None:
        raise last
    c = dict(c, shot_id="s1")
    b = dict(use="personal_noncommercial", ai="none", shots=[dict(shot_id="s1")])
    c["gate"] = gate.evaluate(src, c["license"], b, True, c["provenance"])
    validate("candidate", c)
    if src["id"] not in ("dareful", "nasa_svs") and not c["file_url"]:
        raise FscError(f"{c['asset_id']}: no file address")
    return c


def terms(http, src):
    """None when the terms page is not on one of the source's own hosts or cannot be read: reported as not checked, never as unchanged."""
    u = src.get("terms_url")
    if not u or urlsplit(u).hostname not in src["hosts"] or "#" in u:
        return None
    try:
        return health.terms_hash(http.get(u, src).decode("utf-8", "replace"))
    except FscError:
        return None


def run(http, S, old, today, only=None, pause=time.sleep):
    rows, new = [], dict(old["sources"])
    for i in sorted(providers.ADAPTERS):
        if only and i != only:
            continue
        src, err, c, t0 = S[i], None, None, time.monotonic()
        for n in range(2):
            try:
                c, err = probe(http, src), None
                break
            except FscError as e:
                err = str(e)
                if SKIP.search(err):
                    break
                pause(0 if n else 20)
        if err and SKIP.search(err):
            rows.append(dict(id=i, result="skipped", error=err))
            print(i, "skipped", flush=True)
            continue
        h = terms(http, src) if not err else None     # a dead host would cost minutes more
        o = old["sources"].get(i)
        changed = bool(h and o and o["terms_sha256"] and o["terms_sha256"] != h)
        if changed:     # one odd response is not a new page: read again before raising an alert
            pause(60)
            h = terms(http, src) or h
            changed = o["terms_sha256"] != h
        new[i] = health.step(o, not err, err, h, today)
        rows.append(dict(id=i, result="fail" if err else "ok", error=err, asset_id=c and c["asset_id"], verdict=c and c["gate"]["verdict"],
                         terms="not_checked" if not h else "changed" if changed else "ok", failures=new[i]["failures"]))
        print(i, rows[-1]["result"], f"{time.monotonic() - t0:.0f}s", flush=True)
    return rows, validate("health", dict(schema_version="1.0.0", generated_at=today.isoformat(), sources=new))


def report(rows):
    """Markdown for an issue. Upstream text is untrusted: code spans only, no mentions, no links."""
    c = lambda s: "`" + str(s or "").replace("`", "'").replace("|", "/").replace("\n", " ")[:200] + "`"
    bad = [r for r in rows if r["result"] == "fail" or r.get("terms") == "changed"]
    out = ["| source | result | terms | weeks failing | error |", "|---|---|---|---|---|"]
    out += [f"| {r['id']} | {r['result']} | {r.get('terms', '-')} | {r.get('failures', '-')} | {c(r['error'])} |" for r in rows]
    tail = "\n\nA changed terms page must be read again by a person before its licence row is trusted; set `verify_status: stale` until then." if any(r.get("terms") == "changed" for r in rows) else ""
    return "\n".join(out) + tail + "\n", bool(bad)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true", help="update data/health.json")
    p.add_argument("--only")
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args(argv)
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = ROOT / "data/health.json"
    rows, new = run(Http(), load_sources(), read_json(f, "health"), dt.datetime.now(dt.timezone.utc).date(), a.only)
    md, bad = report(rows)
    (out / "report.md").write_text(md, "utf-8")
    write_json(out / "smoke.json", dict(schema_version="1.0.0", rows=rows))
    if a.write:
        write_json(f, new)
    print(md)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
