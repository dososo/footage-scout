"""T2: page-read sources. robots.txt is enforced by Http on every request. Licences come from the reviewed
source table; a page can only make the outcome stricter, never looser."""
import re
from urllib.parse import urlencode, urlsplit
from .. import licenses
from ..core import FscError
from . import cand, https, media, native, number, text

THIRD = re.compile(r"copyright|©|courtesy|all rights reserved|getty|shutterstock|pond5|licensed", re.I)
STOCK = re.compile(r"coverr|pexels|pixabay|videvo|mixkit|mazwai|vidsplay|dareful|videezy|life ?of ?vids", re.I)


def page(s, url):
    return s.http.get(url, s.src).decode("utf-8", "replace")


def meta(t, prop):
    m = re.search(rf'<meta[^>]+property="{re.escape(prop)}"[^>]+content="([^"]*)"', t)
    return m[1] if m else None


def seconds(v):
    v = text(v) or ""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", v)
    if m:
        n = [int(x) for x in m.groups() if x is not None]
        return n[0] * 60 + n[1] if len(n) == 2 else n[0] * 3600 + n[1] * 60 + n[2]
    m = re.fullmatch(r"(?:(\d+) h )?(?:(\d+) m )?(\d+) s", v)
    return sum(int(x or 0) * k for x, k in zip(m.groups(), (3600, 60, 1))) if m else None


def slugs(found, n):
    return list(dict.fromkeys(found))[:n]


class Page:
    ID = r"[a-z0-9][a-z0-9_-]{0,119}"

    def __init__(s, http, src): s.http, s.src = http, src

    def page_id(s, url):
        u = urlsplit(url)
        m = re.fullmatch(re.escape(s.PATH) + f"({s.ID})/?", u.path)
        return f"{s.src['id']}:{m[1]}" if m and u.hostname == s.HOST else None

    def url(s, i): return f"https://{s.HOST}{s.PATH}{i}/"


class Djangoplicity(Page):
    """ESA/Hubble, ESA/Webb, ESO and NOIRLab run the same public archive software."""
    SITES = dict(esahubble=("esahubble.org", "/videos/"), esawebb=("esawebb.org", "/videos/"),
                 eso=("www.eso.org", "/public/videos/"), noirlab=("noirlab.edu", "/public/videos/"))
    NAV = {"viewall", "archive", "search", "feed", "videoframe", "subscribe"}
    RANK = ("hd_1080p25_screen", "hd_1080_screen", "hd_and_apple", "ultra_hd", "medium_podcast")

    def __init__(s, http, src):
        super().__init__(http, src)
        s.HOST, s.PATH = s.SITES[src["id"]]

    def search(s, q, n):
        t = page(s, f"https://{s.HOST}{s.PATH}?" + urlencode(dict(search=q)))
        ids = re.findall(rf'data-url="{re.escape(s.PATH)}({s.ID})/"|<a href="{re.escape(s.PATH)}({s.ID})/"[^>]*>\s*<span class="title"', t)
        return [f"{s.src['id']}:{i}" for i in slugs((a or b for a, b in ids if (a or b) not in s.NAV), n)]

    def resolve(s, aid):
        i = native(aid, s.ID)
        t = page(s, s.url(i))
        row = dict(re.findall(r'<t[hd] (?:class="title" ?)?(?:scope="row")?>([^<]+):</t[hd]><td[^>]*>(.*?)</td>', t, re.S))
        if i in s.NAV or text(row.get("Id")) != i:
            raise FscError(f"asset not found: {aid}")
        files = {}
        for u in re.findall(r'href="(https?://[^"]+)"', t):
            p = urlsplit(u)
            m = re.search(rf"/videos/([a-z0-9_]+)/{re.escape(i)}\.(?:mp4|m4v|mov)$", p.path)
            if m and p.hostname in s.src["hosts"] and not p.query:
                files[m[1]] = https(u)
        k = next((k for k in s.RANK if k in files), None)
        credit = re.search(r'<div class="credit">(.*?)</div>', t, re.S)
        author = text(credit[1], 4000) if credit else None
        # soundtracks and third-party inserts are outside the CC BY grant, and cannot be excluded from metadata: R7 always warns
        lic = licenses.from_source(s.src, third=True)
        if not author or THIRD.search(author):
            lic = licenses.make(third=True, url=s.src["terms_url"])
        hd = (1920, 1080) if k and k.startswith("hd_1080") else (None, None)
        c = cand(s.src, i, meta(t, "og:title"), None, s.url(i), files.get(k), lic, None, media(seconds(row.get("Duration")), *hd))
        c["author"] = author
        plain = re.sub(r"not AI[- ]generated", "", text(t, 10 ** 7) or "", flags=re.I)
        if re.search(r"(this|material|video|image)[^.]{0,40}\b(is|was|are|were)\b[^.]{0,20}AI[- ]generated", plain, re.I):
            c["provenance"] = "ai_generated"
        return c

    def previews(s, aid):
        u = https(meta(page(s, s.url(native(aid, s.ID))), "og:image"))
        return [u] if u else []


class IsoRepublic(Page):
    HOST, PATH = "isorepublic.com", "/video/"

    def search(s, q, n):
        t = page(s, "https://isorepublic.com/?" + urlencode(dict(s=q, post_type="video_post")))
        return [f"isorepublic:{i}" for i in slugs(re.findall(rf'href="https://isorepublic\.com/video/({s.ID})/"', t), n)]

    def resolve(s, aid):
        i = native(aid, s.ID)
        t = page(s, s.url(i))
        row = {text(k): v for k, v in re.findall(r"<li>\s*<em>([^<]+)</em>\s*<strong[^>]*>(.*?)</li>", t, re.S)}
        if "Dimensions" not in row:
            raise FscError(f"asset not found: {aid}")
        m = re.search(r'<source src="(https://isorepublic\.com/wp-content/uploads/[^"?#]+\.mp4)"', t)
        wh = re.findall(r"\d+", text(row["Dimensions"]) or "")
        author = text(row.get("Author"))
        # some clips were first published on other stock sites: their licence, not this site's, decides
        own = author and re.fullmatch(r"iso ?republic", author, re.I)
        lic = licenses.make(third=True, url=s.src["terms_url"]) if not author or STOCK.search(author) else licenses.from_source(s.src, third=not own)
        title = re.sub(r"\s+(Royalty Free|Free) Stock Video.*$", "", text(meta(t, "og:title")) or "", flags=re.I)
        return cand(s.src, i, title, author, s.url(i), https(m[1]) if m else None, lic, None,
                    media(seconds(row.get("Duration")), *(wh if len(wh) == 2 else (None, None))))

    def previews(s, aid):
        u = https(meta(page(s, s.url(native(aid, s.ID))), "og:image"))
        return [u] if u else []


class Dareful(Page):
    """Search and link only: the site streams through Mux and exposes no direct file."""
    HOST, PATH = "dareful.com", "/"

    def search(s, q, n):
        t = page(s, "https://dareful.com/?" + urlencode(dict(s=q)))
        return [f"dareful:{i}" for i in slugs(re.findall(rf'href="https://dareful\.com/({s.ID})/"[^>]*class="grid-link"', t), n)]

    def resolve(s, aid):
        i = native(aid, s.ID)
        t = page(s, s.url(i))
        x = text(t, 10 ** 7) or ""
        d, r = re.search(r"Duration — (\d+:\d\d)\b", x), re.search(r"Resolution — (\d+) x (\d+)", x)
        if not r:
            raise FscError(f"asset not found: {aid}")
        cc = re.search(r"License — Creative Commons Attribution 4\.0 International", x)
        title = re.search(r"<title>(.*?)</title>", t, re.S)
        title = re.sub(r"\s+Royalty Free Stock Video.*$", "", text(title[1]) or "") if title else None
        lic = licenses.from_source(s.src) if cc else licenses.make(url=s.src["terms_url"])
        return cand(s.src, i, title, "Dareful", s.url(i), None, lic, None, media(seconds(d[1]) if d else None, r[1], r[2]))

    def previews(s, aid):
        u = https(meta(page(s, s.url(native(aid, s.ID))), "og:image"))
        return [u] if u and urlsplit(u).hostname in s.src["hosts"] else []
