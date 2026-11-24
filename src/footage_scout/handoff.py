"""T3 / T4: a table of pages for the user to open, and pairing of files the user dropped into <project>/inbox. Never opens a page itself."""
import configparser, ctypes, os, pathlib, plistlib, re, sys
from urllib.parse import quote, urlsplit
from . import providers, register as reg
from .core import FscError, atomic_write, safe_path, write_json

# search pages opened by the user in their own browser; not probed by this tool
SEARCH = {
    "pexels": "https://www.pexels.com/search/videos/{q}/",
    "pixabay": "https://pixabay.com/videos/search/{q}/",
    "flickr_cc": "https://www.flickr.com/search/?media=videos&license=4%2C5%2C9%2C10&text={q}",
    "nara": "https://catalog.archives.gov/search?q={q}",
    "dvids": "https://www.dvidshub.net/search/?q={q}&filter%5Btype%5D=video",
    "youtube_cc": "https://www.youtube.com/results?search_query={q}&sp=EgIwAQ%253D%253D",
    "europeana": "https://www.europeana.eu/en/search?query={q}&qf=TYPE%3A%22VIDEO%22",
    "vimeo_cc": "https://vimeo.com/search?q={q}",
}
MAX_FILES = 50


def links(brief, sources, per_shot=4):
    rows = []
    for shot in brief["shots"]:
        t, q = set(shot["topics"]), shot["queries"][0]
        c = [s for s in sources.values() if s["tier"] in ("T3", "T4") and s["status"] == "active" and s["hosts"]
             and (t & {*s["topics"]} or "general" in s["topics"])]
        c.sort(key=lambda s: (-len(t & {*s["topics"]}), s["tier"], s["source_trust"], s["id"]))
        for s in c[:per_shot]:
            u = SEARCH.get(s["id"])
            url = u.format(q=quote(q, safe="")) if u else f"https://{s['hosts'][0]}/"
            rows.append(dict(shot_id=shot["shot_id"], source_id=s["id"], url=url, kind="search" if u else "home", query=q,
                             gate_default=s["gate_default"], terms_url=s.get("terms_url")))
    return rows


def _cell(s): return re.sub(r"([\\|`<>\[\]*_])", r"\\\1", " ".join(s.split()))


def write_links(root, brief, sources):
    rows = links(brief, sources)
    root = pathlib.Path(root).resolve()
    inbox = safe_path(root, "inbox")
    inbox.mkdir(parents=True, exist_ok=True)
    for s in brief["shots"]:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", s["shot_id"]):
            safe_path(inbox, s["shot_id"]).mkdir(exist_ok=True)
    md = ["# 直达链接表", "", "在浏览器里打开链接,自己核对许可后下载。把文件放进 `inbox/<镜头编号>/`,再运行 `fsc inbox`。",
          "如果浏览器没有记下来源页,在视频旁边放一个同名文本文件(例如 `a.mp4.txt`),里面只写素材页网址。", "",
          "| 镜头 | 找什么 | 来源 | 链接 | 登记后的状态 |", "|---|---|---|---|---|"]
    desc = {s["shot_id"]: s["description"] for s in brief["shots"]}
    for r in rows:
        md.append(f"| {_cell(r['shot_id'])} | {_cell(desc[r['shot_id']])} | {r['source_id']} | <{r['url']}>{'' if r['kind'] == 'search' else '(首页,自行搜索)'} | "
                  + ("待人工清权(HOLD)" if r["gate_default"] == "hold" else "按规则判定,未逐条核验") + " |")
    atomic_write(safe_path(root, "LINKS.md"), ("\n".join(md) + "\n").encode())
    write_json(safe_path(root, "links.json"), dict(schema_version="1.0.0", links=rows))
    return rows


def _xattr(path, name):
    try:
        if sys.platform == "darwin":
            lib = ctypes.CDLL(None, use_errno=True)
            lib.getxattr.restype = ctypes.c_ssize_t
            lib.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
            buf = ctypes.create_string_buffer(65536)
            n = lib.getxattr(os.fsencode(path), name.encode(), buf, 65536, 0, 1)    # 1 = XATTR_NOFOLLOW
            return buf.raw[:n] if n > 0 else None
        return os.getxattr(path, name, follow_symlinks=False)
    except (OSError, AttributeError):
        return None


def origin(path):
    """Page URLs the browser recorded with the file. Untrusted: only used to look up a known source host."""
    out = []
    if sys.platform == "darwin":
        b = _xattr(path, "com.apple.metadata:kMDItemWhereFroms")
        if b:
            try:
                v = plistlib.loads(b, fmt=plistlib.FMT_BINARY)
                out = [x for x in v if isinstance(x, str)][::-1] if isinstance(v, list) else []     # [file, page] -> page first
            except Exception:       # malformed attribute written by anything
                out = []
    elif sys.platform == "win32":
        try:
            t = pathlib.Path(str(path) + ":Zone.Identifier").read_text("utf-8", "replace")[:8192]
            out = [m[1].strip() for k in ("ReferrerUrl", "HostUrl") if (m := re.search(rf"(?m)^{k}=(.+)$", t))]
        except OSError:
            pass
    else:
        out = [b.decode("utf-8", "replace") for k in ("user.xdg.referrer.url", "user.xdg.origin.url") if (b := _xattr(path, k))]
    return out


def sidecar(path):
    for ext in (".txt", ".url", ".webloc"):
        p = path.with_name(path.name + ext)
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 8192:
            continue
        b = p.read_bytes()
        try:
            if ext == ".webloc":
                return str(plistlib.loads(b)["URL"])
            t = b.decode("utf-8-sig")
            if ext == ".url":
                c = configparser.ConfigParser(interpolation=None, strict=False)
                c.read_string(t)
                return c["InternetShortcut"]["URL"].strip()
            return t.strip()
        except Exception:           # unreadable sidecar: the file stays unpaired and is reported
            continue
    return None


def page_for(path, sources):
    side = sidecar(path)
    for u in ([side] if side else origin(path)):
        try:
            p = urlsplit(u)
        except ValueError:
            continue
        # a direct file URL is not a page that states a licence
        if p.scheme == "https" and p.path not in ("", "/") and pathlib.PurePosixPath(p.path).suffix.lower() not in providers.VIDEO and any(p.hostname in s["hosts"] for s in sources.values()):
            return u
    return None


def shot_for(path, inbox, page, brief, rows, sources):
    ids = [s["shot_id"] for s in brief["shots"]]
    rel = path.relative_to(inbox).parts
    if len(rel) == 2:
        return rel[0] if rel[0] in ids else None
    pre = [i for i in ids if re.match(re.escape(i) + r"[-_. ]", path.name)]
    if len(pre) == 1:
        return pre[0]
    if len(ids) == 1:
        return ids[0]
    if page:
        sid = reg.find_source(page, sources)["id"]
        hit = {r["shot_id"] for r in rows if r["source_id"] == sid}
        if len(hit) == 1:
            return hit.pop()
    return None


def scan(root, brief, sources, make_http=None):
    """Register every file that can be paired without guessing; report the rest. Files in the inbox are never moved or deleted."""
    root = pathlib.Path(root).resolve()
    inbox = safe_path(root, "inbox")
    if not inbox.is_dir():
        raise FscError("no inbox directory; run `fsc links` first")
    files = []
    for p in sorted(inbox.iterdir()):
        if p.is_symlink() or p.name.startswith("."):
            continue
        files += [p] if p.is_file() else sorted(x for x in p.iterdir() if x.is_file() and not x.is_symlink() and not x.name.startswith(".")) if p.is_dir() else []
    files = [p for p in files if p.suffix.lower() in providers.VIDEO]
    rows, done, left = links(brief, sources), [], []
    if len(files) > MAX_FILES:
        left.append(dict(file="", reason=f"only the first {MAX_FILES} files were read"))
    for p in files[:MAX_FILES]:
        rel = p.relative_to(inbox).as_posix()
        page = page_for(p, sources)
        shot = shot_for(p, inbox, page, brief, rows, sources)
        if not page or not shot:
            left.append(dict(file=rel, reason="; ".join((["no known source page recorded: add a text file with the page address"] if not page else [])
                                                         + (["shot unclear: put it in inbox/<shot_id>/"] if not shot else []))))
            continue
        try:
            http = make_http() if make_http and reg.find_source(page, sources)["id"] in providers.ADAPTERS else None
            done.append(dict(file=rel, shot_id=shot, **reg.register(root, brief, shot, page, p, sources, http)))
        except FscError as e:
            left.append(dict(file=rel, reason=str(e)))
    return done, left
