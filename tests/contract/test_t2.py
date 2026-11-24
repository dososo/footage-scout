import re, httpx, pytest
from footage_scout import providers, gate, licenses
from footage_scout.core import load_sources, FscError, validate
from helpers import make
from conftest import TODAY
S = load_sources(); R = httpx.Response
def setup(sid, h):
    x, c, calls = make(lambda r: R(404) if r.url.path.startswith("/robots.txt") else h(r)); return providers.get(x, S[sid]), calls
def check(c, brief):
    c = dict(c, shot_id="s1"); c["gate"] = gate.gate_candidate(c, brief, S, TODAY); validate("candidate", c); return c["gate"]["verdict"]
D = [("esahubble", "hub", "heic1921b", "cdn.esahubble.org", 83), ("esawebb", "webb", "weic2420a", "cdn.esawebb.org", 30),
     ("eso", "eso", "eso2612a", "cdn.eso.org", 446), ("noirlab", "noir", "noirlab1912a", "storage.noirlab.edu", 10)]
@pytest.mark.parametrize("sid,f,i,host,dur", D)
def test_djangoplicity(sid, f, i, host, dur, fx, brief):
    a, calls = setup(sid, lambda r: R(200, content=fx(f"t2_{f}_search.html" if r.url.query else f"t2_{f}_item.html")))
    ids = a.search("a b&c", 5); assert len(ids) == len(set(ids)) == 5 and "search=a+b%26c" in calls[1][1]
    assert not {x.split(":")[1] for x in ids} & {"viewall", "archive", "search", "feed"}
    c = a.resolve(f"{sid}:{i}"); assert c["file_url"].startswith(f"https://{host}/") and "/hd_1080" in c["file_url"] and c["file_url"].endswith(f"{i}.mp4")
    assert c["author"] and c["media"]["duration_s"] == dur and c["license"]["license_id"] == "CC-BY-4.0" and c["license"]["third_party_rights_flag"]
    assert check(c, brief) == "WARN" and c["provenance"] == "unknown"
    assert a.previews(f"{sid}:{i}") == [a.previews(f"{sid}:{i}")[0]] and f"/videoframe/{i}.jpg" in a.previews(f"{sid}:{i}")[0]
    with pytest.raises(FscError, match="not found"): a.resolve(f"{sid}:other1")
    assert a.page_id(f"https://{S[sid]['hosts'][0]}{a.a.PATH}{i}/") == f"{sid}:{i}" and a.page_id(f"https://evil.org{a.a.PATH}{i}/") is None
def test_credit_rules(fx, brief):
    t = fx("t2_noir_item.html").decode()
    for body in (t.replace('<div class="credit">', '<div class="credit">© Getty, '), t.replace('class="credit"', 'class="x"')):
        a, _ = setup("noirlab", lambda r: R(200, text=body)); c = a.resolve("noirlab:noirlab1912a"); assert c["license"]["license_id"] == "UNKNOWN" and check(c, brief) == "HOLD"
def test_ai_marker(fx):
    t = fx("t2_eso_item.html").decode(); assert "<strong>not</strong> AI generated" in t
    a, _ = setup("eso", lambda r: R(200, text=t.replace("<strong>not</strong> AI generated", "AI generated"))); assert a.resolve("eso:eso2612a")["provenance"] == "ai_generated"
def test_foreign_file_host_ignored(fx):
    t = fx("t2_noir_item.html").decode().replace("https://storage.noirlab.edu/", "https://evil.example/")
    a, _ = setup("noirlab", lambda r: R(200, text=t)); assert a.resolve("noirlab:noirlab1912a")["file_url"] is None
def test_eso_ai_disclosure_kept(fx):
    a, _ = setup("eso", lambda r: R(200, content=fx("t2_eso_item.html"))); assert a.resolve("eso:eso2612a")["license"]["ai_use"] == "disclose_ai_modification"
def test_iso(fx, brief):
    t = fx("t2_iso_item.html").decode()
    a, calls = setup("isorepublic", lambda r: R(200, content=fx("t2_iso_search.html")) if r.url.query else R(200, text=t))
    ids = a.search("forest", 3); assert ids[0] == "isorepublic:man-walking-forest" and len(ids) == 3
    c = a.resolve(ids[0]); assert c["title"] == "Man Walking in Forest" and c["author"] == "Coverr" and c["media"] == dict(duration_s=10, width=1920, height=1080)
    assert c["file_url"].endswith(".mp4") and c["license"]["license_id"] == "UNKNOWN" and check(c, brief) == "HOLD"
    base = t; t = base.replace("<strong>Coverr</strong>", "<strong>Beta Films</strong>"); c = a.resolve(ids[0]); assert c["license"]["license_id"] == "CC0-1.0" and check(c, brief) == "WARN"
    t = base.replace("<strong>Coverr</strong>", "<strong>ISO Republic</strong>"); assert check(a.resolve(ids[0]), brief) == "PASS"
    t = base.replace("Dimensions", "x")
    with pytest.raises(FscError, match="not found"): a.resolve(ids[0])
def test_dareful_link_only(fx, brief):
    t = fx("t2_dar_item.html").decode(); a, _ = setup("dareful", lambda r: R(200, content=fx("t2_dar_search.html")) if r.url.query else R(200, text=t))
    ids = a.search("forest", 3); assert ids[0] == "dareful:winter-forest-hike"
    c = a.resolve(ids[0]); assert c["file_url"] is None and c["title"] == "Winter Forest Hike" and c["license"]["license_id"] == "CC-BY-4.0" and check(c, brief) == "PASS" and c["media"]["duration_s"] == 16
    t = t.replace("Creative Commons Attribution 4.0 International", "Some Licence"); assert check(a.resolve(ids[0]), brief) == "HOLD"
def test_no_shutterstock(fx):
    """Affiliate thumbnails on these pages never become candidates or previews."""
    for sid, f in (("dareful", "dar"), ("isorepublic", "iso")):
        a, _ = setup(sid, lambda r: R(200, content=fx(f"t2_{f}_search.html" if r.url.query else f"t2_{f}_item.html")))
        c = a.resolve(a.search("forest", 1)[0]); assert "picdn" not in str(c) and all("picdn" not in u for u in a.previews(c["asset_id"]))
@pytest.mark.parametrize("v,want", [("0:10", 10), ("1:02:03", 3723), ("01 m 23 s", 83), ("30 s", 30), ("1 h 00 m 02 s", 3602), ("abc", None), ("", None), (None, None)])
def test_seconds(v, want):
    from footage_scout.providers.t2 import seconds; assert seconds(v) == want
def test_t1_previews(fx):
    import json
    def one(sid, aid, h): return setup(sid, h)[0].previews(aid)
    a = one("nasa_images", "nasa_images:GSFC_20140421_EarthOrbit_m11525", lambda r: R(200, content=fx("nasa_asset.json"))); assert 0 < len(a) <= 9 and all(u.startswith("https://images-assets.nasa.gov/") for u in a)
    d = json.loads(fx("ia_meta.json")); a = one("ia", "ia:x", lambda r: R(200, json=d)); assert len(a) <= 9 and all(u.startswith("https://archive.org/download/x/") for u in a)
    a = one("commons", "commons:1", lambda r: R(200, json={"query": {"pages": [{"imageinfo": [{"thumburl": "https://upload.wikimedia.org/t.jpg"}]}]}})); assert a == ["https://upload.wikimedia.org/t.jpg"]
    assert one("loc", "loc:1", lambda r: R(200)) == []
def test_dareful_foreign_preview(fx):
    t = re.sub(r'property="og:image" content="[^"]*"', 'property="og:image" content="https://ak.picdn.net/x.jpg"', fx("t2_dar_item.html").decode()); assert "picdn.net/x.jpg" in t
    assert setup("dareful", lambda r: R(200, text=t))[0].previews("dareful:winter-forest-hike") == []
