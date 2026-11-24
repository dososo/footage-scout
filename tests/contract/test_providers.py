import json, re, httpx, pytest
from urllib.parse import parse_qs
from footage_scout import providers, gate
from footage_scout.core import load_sources, FscError, validate
from helpers import make
from conftest import TODAY
S = load_sources(); R = httpx.Response
def setup(sid, h):
    x, c, calls = make(h); return providers.get(x, S[sid]), calls
def check(c, brief):
    c = dict(c, shot_id="s1"); c["gate"] = gate.gate_candidate(c, brief, S, TODAY); validate("candidate", c); return c["gate"]["verdict"]
def test_nasa(fx, brief):
    d = json.loads(fx("nasa_search.json"))
    a, _ = setup("nasa_images", lambda r: R(200, content=fx("nasa_asset.json") if r.url.path.startswith("/asset") else json.dumps(d)))
    ids = a.search("earth", 3); assert ids[0] == "nasa_images:GSFC_20140421_EarthOrbit_m11525"
    c = a.resolve(ids[0]); assert c["file_url"].startswith("https://images-assets.nasa.gov/video/") and c["license"]["license_id"] == "NASA-media"
    assert check(c, brief) == "WARN"
    d["collection"]["items"][0]["data"][0]["description"] = "Copyright 2020 Someone"
    c = a.resolve(ids[0]); assert c["license"]["license_id"] == "UNKNOWN" and check(c, brief) == "HOLD"
def test_commons(fx, brief):
    d = json.loads(fx("commons_search.json")); pg = {str(p["pageid"]): p for p in d["query"]["pages"]}
    def h(r):
        q = parse_qs(r.url.query.decode()); return R(200, json={"query": {"pages": [pg[q["pageids"][0]]]}} if "pageids" in q else d)
    a, _ = setup("commons", h); ids = a.search("forest", 3); assert len(ids) == 3
    cs = {i: a.resolve(i) for i in ids}; c = cs["commons:141534594"]
    assert c["license"]["license_id"] == "CC-BY-3.0" and check(c, brief) == "PASS" and "<" not in c["author"] and "?" not in c["file_url"]
    assert c["media"]["height"] == 2160 and c["bytes_total"] == 226332289
    pg["141534594"]["imageinfo"][0]["extmetadata"]["LicenseUrl"]["value"] = "https://example.com"; assert check(a.resolve("commons:141534594"), brief) == "HOLD"
def test_ia(fx, brief):
    d = json.loads(fx("ia_meta.json"))
    a, calls = setup("ia", lambda r: R(200, content=fx("ia_search.json") if "advancedsearch" in r.url.path else json.dumps(d)))
    c = a.resolve(a.search("train) OR (x", 3)[0]); assert c["file_url"].endswith("us_news_review_issue_5.mp4") and check(c, brief) == "WARN" and c["license"]["third_party_rights_flag"]
    assert "licenseurl" in calls[0][1] and "%29" in calls[0][1] and "+OR+" in calls[0][1] and "train%29+OR" not in calls[0][1]
    d["metadata"].pop("licenseurl"); assert a.resolve(c["asset_id"])["license"]["license_id"] == "UNKNOWN"
@pytest.mark.parametrize("m,v", [(dict(collection=["opensource_movies", "prelinger"]), "WARN"), (dict(collection="opensource_movies"), "HOLD"), (dict(collection=["fav-prelinger"]), "HOLD"), (dict(collection="fav-prelinger"), "HOLD"), (dict(collection=None), "HOLD"),
    (dict(rights="All rights reserved"), "HOLD"), ({"possible-copyright-status": "in copyright"}, "HOLD"), (dict(licenseurl="http://creativecommons.org/licenses/publicdomain/prelinger/"), "HOLD"), (dict(licenseurl="https://evil.example/publicdomain/zero/1.0/"), "HOLD"), (dict(licenseurl="http://creativecommons.org/licenses/by-nc-nd/4.0/"), "BLOCK")])
def test_ia_d16(fx, brief, m, v):
    d = json.loads(fx("ia_meta.json")); d["metadata"].update(m); a, _ = setup("ia", lambda r: R(200, json=d)); assert check(a.resolve("ia:us_news_review_issue_5"), brief) == v
def test_ia_nasa_still_hold(fx, brief):
    d = json.loads(fx("ia_meta.json")); a, calls = setup("ia_nasa", lambda r: R(200, json=d)); c = a.resolve("ia_nasa:us_news_review_issue_5"); assert check(c, brief) == "HOLD" and c["license"]["license_id"] == "UNKNOWN"
def test_ia_nasa_search_unfiltered(fx):
    a, calls = setup("ia_nasa", lambda r: R(200, content=fx("ia_search.json"))); a.search("moon", 1); assert "licenseurl" not in calls[0][1] and "nasa" in calls[0][1]
@pytest.mark.parametrize("m", [{"access-restricted-item": "true"}, dict(collection=["prelinger", "stream_only"])])
def test_ia_restricted(fx, m):
    d = json.loads(fx("ia_meta.json")); d["metadata"].update(m); a, _ = setup("ia", lambda r: R(200, json=d)); assert a.resolve("ia:us_news_review_issue_5")["file_url"] is None
def test_ia_private_file(fx):
    d = json.loads(fx("ia_meta.json")); d["files"][0]["private"] = "true"; a, _ = setup("ia", lambda r: R(200, json=d)); assert a.resolve("ia:us_news_review_issue_5")["file_url"].endswith("_512kb.mp4")
def test_ia_page_id():
    a, _ = setup("ia", lambda r: R(500)); assert a.page_id("https://archive.org/details/HerdsWes1955") == a.page_id("https://archive.org/details/HerdsWes1955/") == "ia:HerdsWes1955" and all(a.page_id("https://archive.org" + p) is None for p in ("/details/a/b", "/download/a", "/details/"))
def test_loc(fx, brief):
    a, calls = setup("loc", lambda r: R(200, content=fx("loc_item.json" if "/item/" in r.url.path else "loc_search.json")))
    c = a.resolve(a.search("train", 3)[0]); assert c["file_url"].startswith("https://tile.loc.gov/") and check(c, brief) == "HOLD"
    assert all("/search" not in u for _, u in calls) and "/film-and-videos/" in calls[0][1]
def test_openbeelden(fx, brief):
    a, calls = setup("openbeelden", lambda r: R(200, content=fx("ob_list.xml")))
    ids = a.search("bioscopen", 1); assert ids == ["openbeelden:1480524"]
    c = a.resolve(ids[0]); assert c["license"]["license_id"] == "PDM-1.0" and c["file_url"].endswith(".mp4") and check(c, brief) == "PASS"
    a, _ = setup("openbeelden", lambda r: R(200, content=b'<!DOCTYPE x [<!ENTITY a "b">]><x/>'))
    with pytest.raises(FscError): a.search("x", 1)
def test_svs_never_fetchable(brief):
    a, _ = setup("nasa_svs", lambda r: R(200, json={"results": [{"id": 15122}]}))
    c = a.resolve(a.search("earth", 1)[0]); assert c["file_url"] is None and check(c, brief) == "HOLD"
@pytest.mark.parametrize("sid", list(providers.ADAPTERS))
@pytest.mark.parametrize("body", [b"<html>", b"[]", b"null", b'{"a":1}', b'{"collection":{"items":[{}]},"results":[1],"response":{"docs":[2]},"query":{"pages":[3]}}'])
def test_garbage_is_clean_error(sid, body):
    a, _ = setup(sid, lambda r: R(200, content=body))
    for f, x in ((a.search, ("q", 1)), (a.resolve, (f"{sid}:1",))):
        try: f(*x)
        except FscError: pass
@pytest.mark.parametrize("sid", [k for k in providers.ADAPTERS if k != "nasa_images"])
@pytest.mark.parametrize("bad", ["../x", "1/../../x", "1?x=1", "..", "", "1&y"])
def test_bad_ids(sid, bad):
    a, calls = setup(sid, lambda r: R(200, json={}))
    with pytest.raises(FscError): a.resolve(f"{sid}:{bad}")
    assert calls == []
def test_commons_nonfree(fx, brief):
    p = next(p for p in json.loads(fx("commons_search.json"))["query"]["pages"] if p["pageid"] == 141534594)
    p["imageinfo"][0]["extmetadata"]["NonFree"] = {"value": "true"}
    a, _ = setup("commons", lambda r: R(200, json={"query": {"pages": [p]}})); assert check(a.resolve("commons:141534594"), brief) == "HOLD"
def test_entity_after_prolog_refused():
    a, _ = setup("openbeelden", lambda r: R(200, content=b"<!--" + b"x"*5000 + b'--><!DOCTYPE x [<!ENTITY a "b">]><x/>'))
    with pytest.raises(FscError, match="DTD"): a.search("x", 1)
