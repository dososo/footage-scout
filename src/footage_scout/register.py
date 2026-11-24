"""T3 / T4 hand-off: record a file the user downloaded themselves. Never downloads, never upgrades a verdict."""
import datetime as dt, hashlib, os, pathlib, shutil, stat, tempfile
from urllib.parse import urlsplit
from . import gate, licenses, manifest as M, media, providers
from .core import FscError, ProjectLock, atomic_write, canonical, digest, safe_path
from .fetch import MAX_BYTES
from .http import check_url


def find_source(url, sources):
    host = urlsplit(url).hostname
    hits = [s for s in sources.values() if host in s["hosts"]]
    if not hits:
        raise FscError(f"page host is not a known source: {host}")
    return hits[0]


def register(root, brief, shot_id, page, file, sources, http=None, title=None, author=None, today=None):
    u = urlsplit(page)
    page = f"{u.scheme}://{u.netloc}{u.path}"       # query and fragment can carry tokens
    src = find_source(page, sources)
    check_url(page, src, True)
    if u.path in ("", "/"):
        raise FscError("give the page of the clip itself, not the site home page")
    shot = next((s for s in brief["shots"] if s["shot_id"] == shot_id), None)
    if shot is None:
        raise FscError(f"unknown shot: {shot_id}")
    f = pathlib.Path(file).expanduser()
    if f.is_symlink():
        raise FscError("symlink refused")
    ext = f.suffix.lower()
    if ext not in providers.VIDEO:
        raise FscError(f"file type refused: {ext!r}")
    aid = live = None
    if src["id"] in providers.ADAPTERS and http:
        ad = providers.get(http, src)
        aid = ad.page_id(page)
        live = ad.resolve(aid) if aid else None
    if live:
        lic, title, author, page, prov = live["license"], live["title"], live["author"], live["source_page"], live["provenance"]
    else:
        aid = f"{src['id']}:page-{hashlib.sha256(page.encode()).hexdigest()[:16]}"
        # the user's own words never become licence terms; nothing about the single item was verified
        lic, prov = licenses.from_source(src, third=True), "unknown"
        title, author = providers.text(title) or f.stem, providers.text(author)
    g = gate.evaluate(src, lic, brief, shot.get("will_edit", True), prov, today)
    if g["verdict"] == "BLOCK":
        raise FscError(f"licence gate BLOCK {g['rules']}: not registered")
    root = pathlib.Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with ProjectLock(root) as lk:
        m = M.load(root, brief["title"], digest(brief))
        try:
            fd = os.open(f, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        except OSError as e:
            raise FscError(f"cannot open file: {e.strerror}") from e
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= MAX_BYTES:
            os.close(fd)
            raise FscError("not a regular file, empty, or above the size limit")
        with os.fdopen(fd, "rb") as i:
            d = safe_path(root, "media")
            d.mkdir(exist_ok=True)
            tfd, tmp = tempfile.mkstemp(dir=d, prefix=".part-", suffix=ext)
            try:
                h, n = hashlib.sha256(), 0
                with os.fdopen(tfd, "wb") as o:
                    while b := i.read(1 << 20):
                        n += len(b)
                        if n > MAX_BYTES:
                            raise FscError("file grew above the size limit")
                        h.update(b)
                        o.write(b)
                        lk.beat()
                    o.flush()
                    os.fsync(o.fileno())
                sha = h.hexdigest()
                old = M.existing(root, m, aid)
                if old:
                    if old["sha256"] != sha:
                        raise FscError("this page is already registered with a different file")
                    return dict(asset_id=aid, path=old["path"], sha256=sha, gate=old["gate"], status="already_present")
                med = media.probe(tmp)
                if med is None and shutil.which("ffprobe"):
                    raise FscError("file has no readable video stream")
                snap = canonical(dict(source=src, license=lic, source_page=page, brief=brief, registered=True))
                sh = hashlib.sha256(snap).hexdigest()
                safe_path(root, "terms").mkdir(exist_ok=True)
                atomic_write(safe_path(root, "terms", sh + ".json"), snap)
                name = f"{src['id']}_{hashlib.sha256(aid.encode()).hexdigest()[:16]}{ext}"
                os.replace(tmp, safe_path(root, "media", name))
            finally:
                pathlib.Path(tmp).unlink(missing_ok=True)
        g = dict(g, artifact_sha256=sha)
        M.put(root, m, dict(
            asset_id=aid, source_id=src["id"], path=f"media/{name}", sha256=sha, source_page=page, download_host=urlsplit(page).hostname,
            tasl=dict(title=title, author=author, source=page, license=lic["license_id"] + (f" ({lic['terms_url']})" if "terms_url" in lic else "")),
            provenance=prov, license=dict(lic, terms_snapshot_sha256=sh), gate=g, media=med, segment=None,
            downloaded_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), modifications=[]))
    return dict(asset_id=aid, path=f"media/{name}", sha256=sha, gate=g, status="registered")
