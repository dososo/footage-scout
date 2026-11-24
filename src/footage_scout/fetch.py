import datetime as dt, hashlib, os, pathlib, tempfile
from urllib.parse import urlsplit
import httpx
from . import gate, manifest as M, providers
from .core import FscError, ProjectLock, canonical, digest, file_sha256, safe_path, validate, write_json, atomic_write
from .http import check_url
from .media import probe

MAX_BYTES, MAX_DL = 2 << 30, 30
TYPES = ("video/", "application/octet-stream", "application/ogg", "binary/octet-stream")


def pending(cs, sources, today=None, only=None):
    if digest(cs["brief"]) != cs["brief_sha256"]:
        raise FscError("brief changed after search; search again")
    todo, held = [], []
    if only and set(only) - {c["asset_id"] for c in cs["candidates"]}:
        raise FscError("--only names an asset that is not in the list")
    for c in cs["candidates"]:
        if only and c["asset_id"] not in only:
            continue
        g = gate.gate_candidate(c, cs["brief"], sources, today)
        if g["verdict"] in ("PASS", "WARN") and c["file_url"]:
            todo.append((c, g))
        else:
            held.append((c, g))
    # one physical asset may serve several shots: every shot must pass, download once
    bad = {c["asset_id"] for c, _ in held}
    uniq = {}
    for c, g in todo:
        if c["asset_id"] in bad:
            continue
        o = uniq.get(c["asset_id"])
        if o is None:
            uniq[c["asset_id"]] = (c, g)
        else:
            if {k: v for k, v in o[0].items() if k in KEY} != {k: v for k, v in c.items() if k in KEY}:
                raise FscError(f"conflicting records for {c['asset_id']}")
            v = max(o[1]["verdict"], g["verdict"], key=gate.ORDER.index)
            uniq[c["asset_id"]] = (o[0], dict(verdict=v, rules=sorted({*o[1]["rules"], *g["rules"]})))
    return list(uniq.values()), held


KEY = ("asset_id", "source_id", "file_url", "bytes_total", "license", "provenance", "source_page", "title", "author")


def token(cs, todo):
    return digest([cs["brief_sha256"], [[{k: c[k] for k in KEY}, g] for c, g in todo]])


def origin_check(c, http, sources):
    live = providers.get(http, sources[c["source_id"]]).resolve(c["asset_id"])
    for k in KEY:
        if k != "bytes_total" and live.get(k) != c.get(k):
            raise FscError(f"{c['asset_id']}: {k} differs from the source; search again")


def prepare(path, cs, http, sources, today=None, only=None):
    """Verify each item against its origin, learn its size, then issue the token."""
    with ProjectLock(pathlib.Path(path).parent) as lk:
        todo, held = pending(cs, sources, today, only)
        ok, errs = {}, []
        for c, _ in todo:
            lk.beat()
            try:
                origin_check(c, http, sources)
                with http.request("HEAD", c["file_url"], sources[c["source_id"]]) as (r, _h):
                    n = r.headers.get("content-length", "")
                if not n.isdigit() or not 0 < int(n) <= MAX_BYTES:
                    raise FscError(f"size unknown or above {MAX_BYTES} bytes")
                ok[c["asset_id"]] = int(n)
            except FscError as e:
                errs.append(dict(asset_id=c["asset_id"], error=str(e)))
        for c in cs["candidates"]:
            if c["asset_id"] in ok:
                c["bytes_total"] = ok[c["asset_id"]]
        validate("candidate_set", cs)
        write_json(path, cs)
        todo, held = pending(cs, sources, today, only)
        return todo, held, errs, token(cs, todo)


def download(c, http, src, root, beat, max_bytes=MAX_BYTES):
    name = f"{c['source_id']}_{hashlib.sha256(c['asset_id'].encode()).hexdigest()[:16]}"
    ext = pathlib.PurePosixPath(urlsplit(c["file_url"]).path).suffix.lower()
    if ext not in providers.VIDEO:
        raise FscError(f"file type refused: {ext!r}")
    d = safe_path(root, "media")
    d.mkdir(exist_ok=True)
    dest = safe_path(root, "media", name + ext)
    h, n = hashlib.sha256(), 0
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as f, http.request("GET", c["file_url"], src) as (r, host):
            if not r.headers.get("content-type", "").lower().startswith(TYPES):
                raise FscError(f"unexpected content-type {r.headers.get('content-type', '')[:60]!r}")
            for b in r.iter_bytes(1 << 20):
                n += len(b)
                if n > max_bytes or n > c["bytes_total"]:
                    raise FscError("download exceeds confirmed size")
                h.update(b)
                f.write(b)
                beat()
            f.flush()
            os.fsync(f.fileno())
        if n != c["bytes_total"]:
            raise FscError(f"size mismatch: got {n}, confirmed {c['bytes_total']}")
        safe_path(root, "media", name + ext)
        os.replace(tmp, dest)
    except httpx.HTTPError as e:
        raise FscError(f"download interrupted: {type(e).__name__}") from e
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)
    return dest, h.hexdigest(), host


def fetch(path, cs, tok, http, sources, today=None, only=None):
    root = pathlib.Path(path).resolve().parent
    with ProjectLock(root) as lk:
        todo, held = pending(cs, sources, today, only)
        if any(c["bytes_total"] is None for c, _ in todo) or tok != token(cs, todo):
            raise FscError("confirm token does not match the current list; run fetch without --token again")
        m = M.load(root, cs["brief"]["title"], cs["brief_sha256"])
        done, errs, per = [], [], {}
        for c, g in todo:
            src = sources[c["source_id"]]
            try:
                old = M.existing(root, m, c["asset_id"])
                if old:
                    done.append(dict(asset_id=c["asset_id"], path=old["path"], status="already_present"))
                    continue
                if per.get(src["id"], 0) >= MAX_DL:
                    raise FscError("download cap reached for this source")
                per[src["id"]] = per.get(src["id"], 0) + 1
                lk.beat()
                origin_check(c, http, sources)
                check_url(c["file_url"], src, True)
                # snapshot = the licence record this decision was based on (not a copy of the terms page)
                snap = canonical(dict(source=src, license=c["license"], source_page=c["source_page"], brief=cs["brief"]))
                sh = hashlib.sha256(snap).hexdigest()
                safe_path(root, "terms").mkdir(exist_ok=True)
                atomic_write(safe_path(root, "terms", sh + ".json"), snap)
                p, sha, host = download(c, http, src, root, lk.beat)
                med = probe(p)
                m = M.put(root, m, dict(
                    asset_id=c["asset_id"], source_id=src["id"], path=f"media/{p.name}", sha256=sha, source_page=c["source_page"],
                    download_host=host, tasl=dict(title=c["title"], author=c["author"], source=c["source_page"],
                    license=c["license"]["license_id"] + (f" ({c['license']['terms_url']})" if "terms_url" in c["license"] else "")),
                    provenance=c["provenance"], license=dict(c["license"], terms_snapshot_sha256=sh),
                    gate=dict(g, artifact_sha256=sha), media=med or c.get("media"), segment=None,
                    downloaded_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), modifications=[]))
                done.append(dict(asset_id=c["asset_id"], path=f"media/{p.name}", sha256=sha, status="downloaded"))
            except FscError as e:
                errs.append(dict(asset_id=c["asset_id"], error=str(e)))
        return done, held, errs
