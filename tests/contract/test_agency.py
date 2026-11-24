import json, httpx, pytest
from urllib.parse import parse_qs, urlsplit
from footage_scout import gate, providers
from footage_scout.core import FscError, load_sources, validate
from helpers import make
from conftest import TODAY
S = load_sources(); R = httpx.Response
def setup(sid, h):
    x, c, calls = make(lambda r: R(404) if r.url.path.startswith("/robots.txt") else h(r)); return providers.get(x, S[sid]), calls
def check(c, brief):
    c = dict(c, shot_id="s1"); c["gate"] = gate.gate_candidate(c, brief, S, TODAY); validate("candidate", c); return c["gate"]["verdict"]
N = "nps:58216178-F013-4CD1-B876-12195E6079A5"
def nps(fx, f=lambda t: t): return setup("nps", lambda r: R(200, content=fx("nps_search.json")) if r.url.path == "/solr/" else R(200, text=f(fx("nps_item.html").decode())))
def test_nps(fx, brief):
    a, calls = nps(fx); ids = a.search('bison" OR x:(y', 3); assert N in ids and len(ids) == 3
    q = parse_qs(urlsplit(calls[-1][1]).query); assert q["q"] == ["bison or x y"] and '-Is_Sensitive_Video:"true"' in q["fq"] and 'Type:"Video"' in q["fq"]
    c = a.resolve(N); assert c["file_url"].endswith("_1280x720.mp4") and c["media"] == dict(duration_s=24.0, width=1280, height=720) and c["author"] == "NPS/Neal Herbert" and check(c, brief) == "PASS" and a.previews(N)[0].endswith("_splash.jpg")
@pytest.mark.parametrize("a,b,v", [("Copyright Info&#x3a; Public domain", "Audio&#x3a; yes", "WARN"), ("Public domain&#xa;", "Public domain except the music&#xa;", "HOLD"), ("NPS/Neal Herbert", "Jane Doe", "HOLD"), ("NPS/Neal Herbert", "NPS / courtesy of Getty", "HOLD"),
    ("NPS/Neal Herbert", "", "HOLD"), ("Lamar Valley", "Footage courtesy of BBC", "HOLD"), ("NPS/Neal Herbert", "NPSfan", "HOLD"), ("Lamar Valley", "Not Copyright Info&#x3a; Public domain", "HOLD")])
def test_nps_rights(fx, brief, a, b, v): c = nps(fx, lambda t: t.replace(a, b))[0].resolve(N); assert check(c, brief) == v
def test_nps_bad(fx):
    for f in (lambda t: t.replace("og:title", "x"), lambda t: t.replace("Multimedia__Header", "x")):
        with pytest.raises(FscError, match="not found"): nps(fx, f)[0].resolve(N)
    a = nps(fx, lambda t: t.replace("www.nps.gov", "evil.example"))[0]; assert a.resolve(N)["file_url"] is None and a.previews(N) == []
    for i in ("nps:../x", "nps:5821", "nps:58216178-f013-4cd1-b876-12195e6079a5"):
        with pytest.raises(FscError): nps(fx)[0].resolve(i)
    assert nps(fx, lambda t: t.replace('.mp4"', '.mp4?sig=1"'))[0].resolve(N)["file_url"] is None
    assert nps(fx, lambda t: t.replace('.mp4"', '.exe"'))[0].resolve(N)["file_url"] is None
def test_nps_search_drops_foreign(fx): a, _ = setup("nps", lambda r: R(200, json=dict(response=dict(docs=[dict(PageURL="https://evil/x"), dict(), dict(PageURL="/media/video/view.htm?id=58216178-F013-4CD1-B876-12195E6079A5/../x"), dict(PageURL="/media/photo/view.htm?id=58216178-F013-4CD1-B876-12195E6079A5")])))); assert a.search("x", 3) == []
U = "usgs:january-3-2025"
def usgs(fx, n="usgs_item.html", f=lambda t: t): return setup("usgs", lambda r: R(200, text=fx("usgs_search.html").decode() if r.url.query else f(fx(n).decode())))
def test_usgs(fx, brief):
    a, calls = usgs(fx); ids = a.search("glacier & ice", 3); assert len(ids) == len(set(ids)) == 3 and "search_api_fulltext=glacier+ice" in calls[-1][1]
    c = a.resolve(U); assert c["file_url"].endswith("/20250103.mp4") and check(c, brief) == "PASS" and c["author"] == "U.S. Geological Survey" and a.previews(U)[0].startswith("https://d9-wret.")
    assert a.page_id("https://www.usgs.gov/media/videos/abc-1/") == "usgs:abc-1" and a.page_id("https://evil.org/media/videos/abc") is None and a.page_id("https://www.usgs.gov/media/images/abc") is None
def test_usgs_music_held(fx, brief): assert check(usgs(fx, "usgs_item_music.html")[0].resolve(U), brief) == "HOLD"
@pytest.mark.parametrize("a,b", [("<p>Public Domain.</p>", "<p>Copyrighted, used with permission.</p>"), ("<p>Public Domain.</p>", ""), ("USGS videos by", "Video courtesy of ABC, by"), ("<h3>Details</h3>", '<h3>Details</h3><section><span class="inline-label">Credits: </span>Getty Images</section>')])
def test_usgs_rights(fx, brief, a, b): assert a in fx("usgs_item.html").decode(); assert check(usgs(fx, f=lambda t: t.replace(a, b))[0].resolve(U), brief) == "HOLD"
def test_usgs_bad(fx):
    with pytest.raises(FscError, match="not found"): usgs(fx, f=lambda t: t.replace("Sources/Usage", "x"))[0].resolve(U)
    with pytest.raises(FscError, match="not found"): usgs(fx, f=lambda t: t.replace("og:title", "x"))[0].resolve(U)
    assert usgs(fx, f=lambda t: t.replace("usgs-ocapsv2-public-input-media", "evil"))[0].resolve(U)["file_url"] is None
    t = lambda t: t.replace("Download Video", "x") + '<source src="https://usgs-ocapsv2-public-output-media.s3.us-west-2.amazonaws.com/a.mp4"'; assert usgs(fx, f=t)[0].resolve(U)["file_url"].endswith("/a.mp4")
def eol(fx, f=lambda t: t): return setup("nasa_eol", lambda r: R(200, text=f(fx("eol_list.html").decode())))
E1 = "nasa_eol:Europe-at-Night_ISS061_2020-01"
def test_eol(fx, brief):
    a, calls = eol(fx); ids = a.search("meteors", 3); assert ids[0] == "nasa_eol:MeteorShower-Aurora_ISS061_2020-01" and a.search("zzzz", 3) == [] and a.search("zzzz kuwait", 3) == [E1]
    c = a.resolve(E1); assert c["file_url"] == "https://eol.jsc.nasa.gov/BeyondThePhotography/CrewEarthObservationsVideos/videos/Europe-at-Night_ISS061_2020-01/Europe-at-Night_ISS061_2020-01.mp4" and check(c, brief) == "WARN" and "Johnson" in c["author"]
    assert a.previews(E1)[0].endswith("ISS061-E-139962.jpg")
def test_eol_bad(fx, brief):
    with pytest.raises(FscError, match="not found"): eol(fx)[0].resolve("nasa_eol:nope")
    with pytest.raises(FscError, match="no videos"): eol(fx, lambda t: "<html>")[0].search("x", 1)
    assert check(eol(fx, lambda t: t.replace("The series of shots", "Music courtesy of X. The series", 1))[0].resolve(E1), brief) == "HOLD"
    with pytest.raises(FscError): eol(fx, lambda t: t.replace('src="videos/Europe', 'src="videos/../Europe'))[0].resolve(E1)
    assert eol(fx, lambda t: t.replace('poster="videos/Europe', 'poster="videos/../Europe'))[0].previews(E1) == []
X = "<ListBucketResult><Contents><Key>{}</Key><Size>288000000</Size></Contents></ListBucketResult>"
def test_netflix(brief):
    k = "AV1/Chimera/Old/Chimera-AV1-10bit-1920x1080-6191kbps.mp4"; a, calls = setup("netflix_open", lambda r: R(200, text=X.format(k)))
    assert a.search("film", 3) == ["netflix_open:chimera", "netflix_open:meridian"] and a.search("beach", 3) == ["netflix_open:meridian"] and a.search("zzz", 3) == []
    c = a.resolve("netflix_open:chimera"); assert c["bytes_total"] == 288000000 and c["file_url"].startswith("https://s3.amazonaws.com/download.opencontent.netflix.com/AV1/") and check(c, brief) == "WARN"
    assert c["file_url"].endswith("6191kbps.mp4")
    for i in ("netflix_open:other", "netflix_open:../x", "netflix_open:meridian"):
        n = len(calls)
        with pytest.raises(FscError, match="not found|unsafe|bad|invalid"): a.resolve(i)
        assert i.endswith("meridian") or len(calls) == n
def test_coverr_link_only():
    assert S["coverr"]["tier"] == "T3" and "coverr" not in providers.ADAPTERS
