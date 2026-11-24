"""US government page reads (NPS, USGS, NASA EOL) and Netflix Open Content. The same rule as t2: a page can only make
the outcome stricter than the reviewed source table, never looser."""
import re
from html import unescape
from urllib.parse import quote, urlencode, urlsplit
from .. import licenses
from ..core import FscError
from . import cand, https, media, native, text
from .t2 import THIRD, meta, page, seconds, slugs

GUID = r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}"
VID = (".mp4", ".mov", ".m4v", ".webm")


def own_host(s, u):
    u = https(u)
    p = urlsplit(u) if u else None
    return u if p and p.hostname in s.src["hosts"] and not p.query and p.path.lower().endswith(VID) else None


def still(s, t):
    u = https(unescape(meta(t, "og:image") or ""))
    return [u] if u and urlsplit(u).hostname in s.src["hosts"] else []


def words(q): return re.findall(r"\w+", q.lower())


class Nps:
    """The multimedia search the site itself uses; /solr/ is not disallowed by robots.txt."""
    BASE = "https://www.nps.gov/media/video/view.htm?id="

    def __init__(s, http, src): s.http, s.src = http, src

    def search(s, q, n):
        p = [("q", " ".join(words(q))), ("defType", "edismax"), ("fl", "Title,PageURL"), ("fq", '-Is_Sensitive_Video:"true"'),
             ("fq", 'Category:"Multimedia"'), ("fq", 'Type:"Video"'), ("rows", n), ("wt", "json")]
        d = s.http.json("https://www.nps.gov/solr/?" + urlencode(p), s.src)
        ids = [re.fullmatch(rf"/media/video/view\.htm\?id=({GUID})", x.get("PageURL") or "", re.I) for x in d["response"]["docs"]]
        return [f"nps:{i}" for i in slugs((m[1].upper() for m in ids if m), n)]

    def resolve(s, aid):
        i = native(aid, GUID)
        t = page(s, s.BASE + i)
        title = text(meta(t, "og:title"))
        if not title or 'class="Multimedia__Header' not in t:
            raise FscError(f"asset not found: {aid}")
        files = {}
        for u in re.findall(r'<source src="([^"]+)"', t):
            m = re.search(r"_(\d{2,5})x(\d{2,5})\.mp4$", u)
            if own_host(s, u):
                files[(int(m[2]), int(m[1])) if m else (0, 0)] = own_host(s, u)
        h = max(files, default=None)
        credit = re.search(r'<p class="Multimedia__Credit">(.*?)</p>', t, re.S)
        author = text(credit[1], 1000) if credit else None
        raw = unescape(meta(t, "og:description") or "")
        line = re.compile(r"^\s*Copyright Info:[ \t]*Public domain\.?[ \t]*$", re.I | re.M)     # a whole line, nothing added after it
        declared, rest = line.search(raw), line.sub("", raw)
        agency = author and re.match(r"(NPS|National Park Service)\b", author)
        # the site says its media "should not be presumed to be public domain": an item passes only when it says so itself
        if not agency or THIRD.search(author) or THIRD.search(rest):
            lic = licenses.make(third=True, url=s.src["terms_url"])
        else:
            lic = licenses.from_source(s.src, third=not declared)
        d = re.search(r'Multimedia__Subheading">\s*Duration\s*</h2>\s*(?:<p[^>]*>)?\s*([\d:]+|(?:\d+ \w+,? ?)+)', t)
        iso = re.search(r'itemprop="duration" content="P?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"', t)
        sec = sum(int(x or 0) * k for x, k in zip(iso.groups(), (3600, 60, 1))) if iso else seconds(d[1]) if d else None
        return cand(s.src, i, title, author, s.BASE + i, files.get(h), lic, None, media(sec, h[1], h[0]) if h else None)

    def previews(s, aid):
        return still(s, page(s, s.BASE + native(aid, GUID)))


class Usgs:
    HOST, PATH, ID = "www.usgs.gov", "/media/videos/", r"[a-z0-9][a-z0-9-]{0,199}"

    def __init__(s, http, src): s.http, s.src = http, src

    def url(s, i): return f"https://{s.HOST}{s.PATH}{i}"

    def page_id(s, url):
        u = urlsplit(url)
        m = re.fullmatch(re.escape(s.PATH) + f"({s.ID})/?", u.path)
        return f"usgs:{m[1]}" if m and u.hostname == s.HOST else None

    def search(s, q, n):
        t = page(s, "https://www.usgs.gov/products/multimedia-gallery/videos?" + urlencode(dict(search_api_fulltext=" ".join(words(q)))))
        return [f"usgs:{i}" for i in slugs(re.findall(rf'href="{s.PATH}({s.ID})"', t), n)]

    def resolve(s, aid):
        i = native(aid, s.ID)
        t = page(s, s.url(i))
        title = text(meta(t, "og:title"))
        if not title or "<h3>Sources/Usage</h3>" not in t:
            raise FscError(f"asset not found: {aid}")
        use = re.search(r"<h3>Sources/Usage</h3>(.*?)</section>", t, re.S)
        by = re.search(r'<span class="inline-label">(?:Credits?|Attribution):\s*</span>(.*?)</section>', t, re.S)
        about = re.search(r'<section class="description">(.*?)</section>', t, re.S)
        said = [text(x[1], 10 ** 6) or "" for x in (use, by, about) if x]
        declared = re.fullmatch(r"Public Domain\.?", said[0] if use else "", re.I)
        # anything other than the plain public-domain statement, or third-party wording anywhere on the item, is left unresolved
        lic = licenses.make(third=True, url=s.src["terms_url"]) if not declared or any(THIRD.search(x) for x in said[1:]) else licenses.from_source(s.src)
        dl = re.search(r"""href=['"]([^'"]+)['"]>\s*Download Video""", t)
        f = own_host(s, dl[1]) if dl else None
        f = f or next((u for u in map(lambda u: own_host(s, u), re.findall(r'<source src="([^"]+)"', t)) if u), None)
        return cand(s.src, i, title, text(by[1]) if by else "U.S. Geological Survey", s.url(i), f, lic)

    def previews(s, aid):
        return still(s, page(s, s.url(native(aid, s.ID))))


class Eol:
    """One static page lists every time-lapse the crew earth observation team publishes."""
    BASE = "https://eol.jsc.nasa.gov/BeyondThePhotography/CrewEarthObservationsVideos/"
    ID = r"[A-Za-z0-9_-]{1,100}"

    def __init__(s, http, src): s.http, s.src = http, src

    def items(s):
        out = {}
        for b in re.split(r'(?=<div class="filterDiv )', page(s, s.BASE))[1:]:
            k, v = re.search(rf'<a id="({s.ID})"></a>(.*?)</b>', b, re.S), re.search(r'<video\b[^>]*\bsrc="(videos/[A-Za-z0-9_./-]+\.mp4)"', b)
            if k and v and ".." not in v[1]:
                poster, d = re.search(r'<video\b[^>]*\bposter="(videos/[A-Za-z0-9_./-]+\.jpe?g)"', b, re.I), re.search(r"<p>(.*?)</p>", b, re.S)
                cls = re.search(r'filterDiv ([a-z ]*)"', b)
                out.setdefault(k[1], dict(title=text(k[2]), about=text(d[1], 4000) if d else "", tags=cls[1] if cls else "", src=s.BASE + v[1],
                                          poster=s.BASE + poster[1] if poster and ".." not in poster[1] else None))
        if not out:
            raise FscError("nasa_eol: the list page has no videos")
        return out

    def search(s, q, n):
        w, hits = set(words(q)), []
        for i, x in s.items().items():
            head, body = set(words(f"{x['title']} {x['tags']}")), set(words(x["about"] or ""))
            hits.append((-(3 * len(w & head) + len(w & body)), len(hits), i))
        return [f"nasa_eol:{i}" for k, _, i in sorted(hits) if k][:n]

    def resolve(s, aid):
        i = native(aid, s.ID)
        x = s.items().get(i)
        if not x:
            raise FscError(f"asset not found: {aid}")
        lic = licenses.make(third=True, url=s.src["terms_url"]) if THIRD.search(x["about"] or "") else licenses.from_source(s.src, third=True)
        return cand(s.src, i, x["title"], "Earth Science and Remote Sensing Unit, NASA Johnson Space Center", f"{s.BASE}#{i}", x["src"], lic)

    def previews(s, aid):
        x = s.items().get(native(aid, s.ID))
        return [x["poster"]] if x and x["poster"] else []


class Netflix:
    """A fixed list: only finished films small enough to fetch. The bucket is asked whether the object still exists, and how big it is."""
    ROOT = "https://s3.amazonaws.com/download.opencontent.netflix.com"
    FILMS = {
        "meridian": ("Meridian/Meridian_UHD4k5994_HDR_P3PQ.mp4", "Meridian (2016), UHD 59.94p, HDR P3 PQ", "detective noir drama people beach storm cinematic film 1940s hdr"),
        "chimera": ("AV1/Chimera/Old/Chimera-AV1-10bit-1920x1080-6191kbps.mp4", "Chimera (2015), 1920x1080, AV1 10-bit", "dance people restaurant city street cinematic film test"),
    }

    def __init__(s, http, src): s.http, s.src = http, src

    def search(s, q, n):
        w = set(words(q))
        hits = [(-len(w & set(words(f"{k} {f[1]} {f[2]}"))), k) for k, f in s.FILMS.items()]
        return [f"netflix_open:{k}" for c, k in sorted(hits) if c][:n]

    def resolve(s, aid):
        i = native(aid, "[a-z]{1,20}")
        if i not in s.FILMS:
            raise FscError(f"asset not found: {aid}")
        key, title, _ = s.FILMS[i]
        t = page(s, f"{s.ROOT}?" + urlencode({"list-type": 2, "max-keys": 1, "prefix": key}))
        m = re.search(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", t, re.S)
        if not m or m[1] != key:
            raise FscError(f"asset not found: {aid}")
        return cand(s.src, i, title, "Netflix", "https://opencontent.netflix.com/", f"{s.ROOT}/{quote(key)}", licenses.from_source(s.src, third=True), m[2])
