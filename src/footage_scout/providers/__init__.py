"""T1 adapters (T2 in t2.py). search() yields asset ids; resolve() rebuilds a candidate from the live source, so a
candidate file edited by anyone can be checked against its origin before download."""
import html, json, re, xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode, urlsplit
from .. import licenses
from ..core import FscError

VIDEO = (".mp4", ".webm", ".ogv", ".mov", ".m4v", ".mpg", ".mpeg")


def text(v, cap=300):
    if isinstance(v, list):
        v = "; ".join(str(x) for x in v)
    if v is None:
        return None
    v = html.unescape(re.sub(r"<[^>]*>", " ", str(v)))
    v = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]", " ", v)).strip()
    return v[:cap] or None


def number(v):
    try:
        v = float(v)
        return v if 0 < v < 1e15 else None
    except (TypeError, ValueError):
        return None


def media(duration, w, h):
    d, w, h = number(duration), number(w), number(h)
    return dict(duration_s=d, width=int(w), height=int(h)) if d and w and h else None


def https(u):
    if not isinstance(u, str):
        return None
    u = "https:" + u if u.startswith("//") else re.sub(r"^http:", "https:", u)
    return quote(u, safe=":/?&=%~+,;@!$'()*#[]-._") if u.startswith("https://") else None


def native(asset_id, pattern):
    v = asset_id.split(":", 1)[-1]
    if not re.fullmatch(pattern, v) or v in (".", ".."):
        raise FscError(f"bad asset id: {asset_id[:80]!r}")
    return v


def cand(src, aid, title, author, page, url, lic, size=None, med=None):
    c = dict(schema_version="1.0.0", asset_id=f"{src['id']}:{aid}", source_id=src["id"], title=text(title) or "untitled",
             author=text(author), source_page=page, file_url=url, bytes_total=int(size) if number(size) else None,
             tier=src["tier"], provenance="unknown", license=lic)
    if med:
        c["media"] = med
    return c


class Nasa:
    THIRD = re.compile(r"copyright|©|\(c\)|courtesy|all rights reserved|getty|shutterstock|licensed", re.I)

    def __init__(s, http, src): s.http, s.src = http, src

    def search(s, q, n):
        d = s.http.json("https://images-api.nasa.gov/search?" + urlencode(dict(q=q, media_type="video", page_size=n)), s.src)
        return [f"{s.src['id']}:{i['data'][0]['nasa_id']}" for i in d["collection"]["items"][:n]]

    def resolve(s, aid):
        nid = native(aid, r"[^/\\\x00-\x1f]{1,200}")
        d = s.http.json("https://images-api.nasa.gov/search?" + urlencode(dict(nasa_id=nid)), s.src)["collection"]["items"]
        m = next((i["data"][0] for i in d if i["data"][0]["nasa_id"] == nid), None)
        if not m or m.get("media_type") != "video":
            raise FscError(f"asset not found: {aid}")
        a = s.http.json("https://images-api.nasa.gov/asset/" + quote(nid, safe=""), s.src)["collection"]["items"]
        urls = [i["href"] for i in a if i["href"].lower().endswith((".mp4", ".mov"))]
        rank = lambda u: next((k for k, t in enumerate(("~large", "~medium", "~orig", "~small", "~mobile", "~preview")) if t in u), 9)
        marked = bool(s.THIRD.search(json.dumps(m, ensure_ascii=False)))
        # music and identifiable people cannot be excluded from metadata, so R7 always warns; marked items stay UNKNOWN
        lic = licenses.make(third=True, url=s.src["terms_url"]) if marked else licenses.from_source(s.src, third=True)
        return cand(s.src, nid, m.get("title"), m.get("photographer") or m.get("secondary_creator") or
                    (f"NASA/{m['center']}" if m.get("center") else "NASA"), "https://images.nasa.gov/details/" + quote(nid, safe=""),
                    https(min(urls, key=rank)) if urls else None, lic)


    def previews(s, aid):
        nid = native(aid, r"[^/\\\x00-\x1f]{1,200}")
        a = s.http.json("https://images-api.nasa.gov/asset/" + quote(nid, safe=""), s.src)["collection"]["items"]
        u = sorted(https(i["href"]) or "" for i in a if i["href"].lower().endswith((".jpg", ".png")))
        big = [x for x in u if "thumb" in x and "mobile" not in x] or [x for x in u if "thumb" in x] or u
        return big[::max(1, -(-len(big) // 9))]


class Commons:
    API = "https://commons.wikimedia.org/w/api.php?"
    P = dict(action="query", format="json", formatversion=2, prop="imageinfo", iiprop="url|size|mime|extmetadata")

    def __init__(s, http, src): s.http, s.src = http, src

    def _q(s, **k):
        d = s.http.json(s.API + urlencode({**s.P, **k}), s.src)
        if "error" in d:
            raise FscError(f"commons: {text(d['error'].get('code'))}")
        return d.get("query", {}).get("pages", [])

    def search(s, q, n):
        pages = s._q(generator="search", gsrsearch=f"filetype:video {q}", gsrnamespace=6, gsrlimit=n)
        return [f"commons:{p['pageid']}" for p in sorted(pages, key=lambda p: p.get("index", 0))]

    def resolve(s, aid):
        pid = native(aid, r"\d{1,12}")
        p = next((p for p in s._q(pageids=pid) if p.get("pageid") == int(pid) and p.get("imageinfo")), None)
        if not p:
            raise FscError(f"asset not found: {aid}")
        i = p["imageinfo"][0]
        x = {k: v.get("value") for k, v in i.get("extmetadata", {}).items()}
        third = bool(x.get("Restrictions")) or x.get("NonFree") in ("true", True)
        lic = licenses.from_url(x.get("LicenseUrl"), third)
        if lic["license_id"] == "UNKNOWN" and x.get("License") == "pd" and x.get("Copyrighted") == "False":
            lic = licenses.make("Commons-PD-tag", "no", "yes", "yes", third=third, url=https(i["descriptionurl"]))
        if x.get("NonFree") in ("true", True):
            lic = licenses.make(third=True)
        url = https((i["url"]).split("?")[0])
        return cand(s.src, pid, re.sub(r"^File:", "", p["title"]), x.get("Attribution") or x.get("Artist"),
                    https(i["descriptionurl"]), url if str(i.get("mime", "")).startswith(("video/", "application/ogg")) else None,
                    lic, i.get("size"), media(i.get("duration"), i.get("width"), i.get("height")))


    def previews(s, aid):
        pid = native(aid, r"\d{1,12}")
        return [https(i["thumburl"]) for p in s._q(pageids=pid, iiurlwidth=640) for i in p.get("imageinfo", []) if i.get("thumburl")]


class InternetArchive:
    def __init__(s, http, src):
        s.http, s.src = http, src
        s.scope = "collection:nasa" if src["id"] == "ia_nasa" else "collection:prelinger"

    def search(s, q, n):
        words = " ".join(re.findall(r"\w+", q))
        if s.src["id"] == "ia":     # only items that declare a licence can pass the gate (about 1 in 6 Prelinger films)
            words += ") AND licenseurl:(*creativecommons*"
        p = urlencode([("q", f"{s.scope} AND mediatype:movies AND ({words})"), ("fl[]", "identifier"), ("rows", n), ("output", "json")])
        d = s.http.json("https://archive.org/advancedsearch.php?" + p, s.src)
        return [f"{s.src['id']}:{x['identifier']}" for x in d["response"]["docs"]]

    def resolve(s, aid):
        i = native(aid, r"[A-Za-z0-9._-]{1,120}")
        d = s.http.json(f"https://archive.org/metadata/{i}", s.src)
        m = d.get("metadata")
        if not m:
            raise FscError(f"asset not found: {aid}")
        cols = m.get("collection") or []
        cols = cols if isinstance(cols, list) else [cols]
        restricted = m.get("access-restricted-item") in ("true", True) or "stream_only" in cols
        fs = [f for f in d.get("files", []) if f["name"].lower().endswith((".mp4", ".ogv", ".webm", ".mpg", ".mpeg"))
              and f.get("private") not in ("true", True) and not restricted]
        fs.sort(key=lambda f: (not f["name"].lower().endswith(".mp4"), -(number(f.get("height")) or 0), f["name"]))
        f = fs[0] if fs else {}
        # A declared licence counts only inside the curated Prelinger collection; anyone may upload elsewhere and declare anything.
        # A free-text rights statement may contradict the declaration, so it is never read past. The declarer is not verified: third=True.
        ok = s.src["id"] == "ia" and "prelinger" in cols and not m.get("rights") and not m.get("possible-copyright-status")
        lic = licenses.from_url(m.get("licenseurl"), third=True) if ok else licenses.make(third=True)
        return cand(s.src, i, m.get("title"), m.get("creator"), f"https://archive.org/details/{i}",
                    f"https://archive.org/download/{i}/{quote(f['name'])}" if f else None, lic, f.get("size"), media(f.get("length"), f.get("width"), f.get("height")))

    def page_id(s, url):
        m = re.fullmatch(r"/details/([A-Za-z0-9._-]{1,120})/?", urlsplit(url).path)
        return f"{s.src['id']}:{m[1]}" if m else None

    def previews(s, aid):
        i = native(aid, r"[A-Za-z0-9._-]{1,120}")
        fs = [f["name"] for f in s.http.json(f"https://archive.org/metadata/{i}", s.src).get("files", []) if f.get("format") == "Thumbnail"]
        fs = fs[::max(1, -(-len(fs) // 9))]
        return [f"https://archive.org/download/{i}/{quote(n)}" for n in fs]


class Loc:
    def __init__(s, http, src): s.http, s.src = http, src

    def search(s, q, n):
        # /film-and-videos/ only: robots.txt disallows /search
        d = s.http.json("https://www.loc.gov/film-and-videos/?" + urlencode(dict(q=q, fo="json", c=n, fa="online-format:video")), s.src)
        out = []
        for r in d.get("results", []):
            m = re.fullmatch(r"https?://www\.loc\.gov/item/([A-Za-z0-9._-]+)/?", str(r.get("id")))
            if m and not r.get("access_restricted"):
                out.append(f"loc:{m[1]}")
        return out[:n]

    def resolve(s, aid):
        i = native(aid, r"[A-Za-z0-9._-]{1,120}")
        d = s.http.json(f"https://www.loc.gov/item/{i}/?fo=json", s.src)
        fs = [f for r in d.get("resources", []) for g in r.get("files", []) for f in g if str(f.get("mimetype", "")).startswith("video/") and f.get("url")]
        f = fs[0] if fs else {}
        it = d["item"]
        # `rights` is free text: never interpreted, always UNKNOWN -> HOLD
        return cand(s.src, i, it.get("title"), it.get("contributor_names"), f"https://www.loc.gov/item/{i}/", https(f.get("url")),
                    licenses.make(url=s.src["terms_url"]), f.get("size"))


class OpenBeelden:
    B = "https://www.openbeelden.nl/feeds/oai/?"
    N = {"o": "http://www.openarchives.org/OAI/2.0/", "oi": "http://www.openbeelden.nl/oai/"}
    PAGES = 3

    def __init__(s, http, src): s.http, s.src = http, src

    def _xml(s, **k):
        b = s.http.get(s.B + urlencode(k), s.src)
        if b"<!DOCTYPE" in b[:4096].upper() or b"<!ENTITY" in b.upper():
            raise FscError("openbeelden: DTD refused")
        try:
            return ET.fromstring(b)
        except ET.ParseError as e:
            raise FscError("openbeelden: bad XML") from e

    def search(s, q, n):
        # OAI-PMH has no search: scan the newest records (Dutch metadata) and match locally
        words, out, arg = set(re.findall(r"\w+", q.lower())), [], dict(metadataPrefix="oai_oi")
        for _ in range(s.PAGES):
            x = s._xml(verb="ListRecords", **arg)
            for r in x.iterfind(".//o:record", s.N):
                i = r.findtext("o:header/o:identifier", "", s.N).rsplit(":", 1)[-1]
                blob = " ".join(e.text or "" for t in ("title", "subject", "description", "abstract") for e in r.iterfind(f".//oi:{t}", s.N)).lower()
                if i.isdigit() and words & set(re.findall(r"\w+", blob)):
                    out.append(f"openbeelden:{i}")
            tok = x.findtext(".//o:resumptionToken", "", s.N)
            if len(out) >= n or not tok:
                break
            arg = dict(resumptionToken=tok)
        return out[:n]

    def resolve(s, aid):
        i = native(aid, r"\d{1,12}")
        x = s._xml(verb="GetRecord", metadataPrefix="oai_oi", identifier=f"oai:openimages.eu:{i}")
        for r in x.iterfind(".//o:record", s.N):
            if r.findtext("o:header/o:identifier", "", s.N) == f"oai:openimages.eu:{i}":
                return s.parse(r, i)
        raise FscError(f"asset not found: {aid}")

    def parse(s, r, i):
        g = lambda t: r.findtext(f".//oi:{t}", None, s.N)
        ms = [(e.get("format"), e.text or "") for e in r.iterfind(".//oi:medium", s.N)]
        ms = [m for m in ms if m[1].lower().endswith(VIDEO)]
        ms.sort(key=lambda m: (m[0] != "hd", not m[1].lower().endswith(".mp4")))
        return cand(s.src, i, g("title"), g("attributionName") or g("creator"), f"https://www.openbeelden.nl/media/{i}",
                    https(ms[0][1]) if ms else None, licenses.from_url(g("license")))


class Svs:
    """Search only: the item/media response shape has not been verified, so nothing is resolved to a file."""

    def __init__(s, http, src): s.http, s.src = http, src

    def search(s, q, n):
        d = s.http.json("https://svs.gsfc.nasa.gov/api/search/?" + urlencode(dict(search=q, limit=n)), s.src)
        return [f"nasa_svs:{int(r['id'])}" for r in d["results"][:n]]

    def resolve(s, aid):
        i = native(aid, r"\d{1,9}")
        return cand(s.src, i, f"NASA SVS {i}", "NASA Scientific Visualization Studio", f"https://svs.gsfc.nasa.gov/{i}/", None,
                    licenses.make(url=s.src.get("terms_url")))


# bottom import: t2 needs the helpers above
from .t2 import Dareful, Djangoplicity, IsoRepublic  # noqa: E402
from .agency import Eol, Netflix, Nps, Usgs  # noqa: E402

ADAPTERS = dict(nasa_images=Nasa, commons=Commons, ia=InternetArchive, ia_nasa=InternetArchive, loc=Loc,
                openbeelden=OpenBeelden, nasa_svs=Svs,
                esahubble=Djangoplicity, esawebb=Djangoplicity, eso=Djangoplicity, noirlab=Djangoplicity,
                isorepublic=IsoRepublic, dareful=Dareful,
                nps=Nps, usgs=Usgs, nasa_eol=Eol, netflix_open=Netflix)


def get(http, src):
    if src["id"] not in ADAPTERS:
        raise FscError(f"no adapter for {src['id']}")
    return Guard(ADAPTERS[src["id"]](http, src))


class Guard:
    """Unexpected upstream shapes become FscError instead of crashing the run."""

    def __init__(s, a): s.a = a

    def _call(s, f, *x):
        try:
            return f(*x)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
            raise FscError(f"{s.a.src['id']}: unexpected response shape ({type(e).__name__})") from e

    def search(s, q, n): return s._call(s.a.search, q, n)
    def resolve(s, aid): return s._call(s.a.resolve, aid)

    def previews(s, aid):
        """Still images the source itself publishes for an asset (may be empty)."""
        f = getattr(s.a, "previews", None)
        return [u for u in s._call(f, aid) if u][:9] if f else []

    def page_id(s, url):
        f = getattr(s.a, "page_id", None)
        return f(url) if f else None
