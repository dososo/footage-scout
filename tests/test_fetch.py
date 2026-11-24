import json, httpx, pytest
from footage_scout import fetch as F, gate, cli, core
from footage_scout.core import FscError, load_sources, digest, write_json, read_json
from helpers import make
from conftest import TODAY
S = load_sources(); R = httpx.Response; DATA = b"v" * 5000
class World:
    """Fake Commons: serves metadata and bytes; knobs mutate behaviour."""
    def __init__(s, page): s.page = page; s.body = DATA; s.ct = "video/webm"; s.gets = 0; s.cut = False
    def __call__(s, r):
        if r.url.host == "commons.wikimedia.org":
            return R(200, json={"query": {"pages": [s.page]}})
        if r.method == "HEAD": return R(200, headers={"content-length": str(len(DATA)), "content-type": s.ct})
        s.gets += 1
        if s.cut:
            def it():
                yield s.body[:10]
                raise httpx.ReadError("cut")
            return R(200, headers={"content-type": s.ct}, content=it())
        return R(200, headers={"content-type": s.ct}, content=s.body)
@pytest.fixture
def w(fx, brief, tmp_path):
    pg = next(p for p in json.loads(fx("commons_search.json"))["query"]["pages"] if p["pageid"] == 141534594)
    W = World(pg); W.http, W.clock, W.calls = make(W)
    b = cli.normalise(brief); c = dict(F.providers.get(W.http, S["commons"]).resolve("commons:141534594"), shot_id="s1", score=.5, scorer="none")
    c["gate"] = gate.gate_candidate(c, b, S, TODAY)
    W.path = tmp_path/"candidates.json"
    W.cs = dict(schema_version="1.0.0", brief=b, brief_sha256=digest(b), candidates=[c], notices=[]); write_json(W.path, W.cs)
    W.prep = lambda: F.prepare(W.path, W.cs, W.http, S, TODAY); W.go = lambda t: F.fetch(W.path, W.cs, t, W.http, S, TODAY)
    return W
def clean(p): return not [x for x in p.rglob(".*") if x.name.startswith((".part", ".tmp", ".fsc"))]
def test_happy_and_idempotent(w, tmp_path):
    t = w.prep()[3]; done, held, errs = w.go(t); assert done[0]["status"] == "downloaded" and not errs
    m = read_json(tmp_path/"footage_manifest.json", "manifest"); a = m["assets"][0]
    assert a["sha256"] == core.file_sha256(tmp_path/a["path"]) == a["gate"]["artifact_sha256"]
    sh = a["license"]["terms_snapshot_sha256"]; assert core.file_sha256(tmp_path/"terms"/f"{sh}.json") == sh
    assert w.go(t)[0][0]["status"] == "already_present" and w.gets == 1 and clean(tmp_path)
@pytest.mark.parametrize("mut", [lambda c: c.update(file_url="https://upload.wikimedia.org/x.webm"), lambda c: c["license"].update(commercial="no"), lambda c: c.update(bytes_total=1), lambda c: c.update(title="z")])
def test_token_invalidated(w, mut):
    t = w.prep()[3]; mut(w.cs["candidates"][0])
    with pytest.raises(FscError, match="token"): w.go(t)
    assert w.gets == 0
def test_added_item_invalidates(w):
    t = w.prep()[3]; w.cs["candidates"].append(dict(w.cs["candidates"][0], asset_id="commons:2"))
    with pytest.raises(FscError): w.go(t)
def test_no_prepare_no_download(w):
    w.cs["candidates"][0]["bytes_total"] = None
    with pytest.raises(FscError): w.go(F.token(w.cs, F.pending(w.cs, S, TODAY)[0]))
def test_laundered_license_caught(w):
    """A HOLD item edited to look like CC0, with a fresh token, is still refused against the origin."""
    w.page["imageinfo"][0]["extmetadata"]["LicenseUrl"]["value"] = "https://example.com"
    todo, held, errs, t = w.prep(); assert "license differs" in errs[0]["error"]
    done, _, errs = w.go(F.token(w.cs, F.pending(w.cs, S, TODAY)[0])); assert not done and errs and w.gets == 0
def test_hold_never_downloads(w):
    w.cs["candidates"][0]["license"]["commercial"] = "unknown"; todo, held, errs, t = w.prep()
    assert not todo and held and w.go(t)[0] == [] and w.gets == 0
def test_forged_gate_field_ignored(w):
    c = w.cs["candidates"][0]; c["license"]["derivatives"] = "no"; c["gate"] = dict(verdict="PASS", rules=[])
    assert F.pending(w.cs, S, TODAY)[0] == []
def test_one_bad_shot_blocks_asset(w):
    b = w.cs["brief"]; b["shots"][0]["will_edit"] = False; b["shots"].append(dict(b["shots"][0], shot_id="s2", will_edit=True)); w.cs["brief_sha256"] = digest(b)
    c = w.cs["candidates"][0]; c["license"]["derivatives"] = "no"; w.cs["candidates"].append(dict(c, shot_id="s2"))
    assert F.pending(w.cs, S, TODAY)[0] == []
def test_brief_tamper(w):
    w.cs["brief"]["use"] = "commercial"
    with pytest.raises(FscError): w.prep()
@pytest.mark.parametrize("k,v", [("cut", True), ("body", DATA + b"x"), ("body", DATA[:-1]), ("ct", "text/html")])
def test_failed_download_leaves_nothing(w, tmp_path, k, v):
    t = w.prep()[3]; setattr(w, k, v); done, _, errs = w.go(t)
    assert not done and errs and list((tmp_path/"media").iterdir()) == [] and not (tmp_path/"footage_manifest.json").exists() and clean(tmp_path)
def test_symlink_media(w, tmp_path, tmp_path_factory):
    t = w.prep()[3]; o = tmp_path_factory.mktemp("o"); (tmp_path/"media").symlink_to(o); done, _, errs = w.go(t)
    assert not done and errs and list(o.iterdir()) == []
def test_changed_file_not_overwritten(w, tmp_path):
    t = w.prep()[3]; w.go(t); f = next((tmp_path/"media").iterdir()); f.write_bytes(b"mine")
    done, _, errs = w.go(t); assert errs and f.read_bytes() == b"mine"
def test_only(w):
    w.cs["candidates"].append(dict(w.cs["candidates"][0], asset_id="commons:2"))
    t = F.prepare(w.path, w.cs, w.http, S, TODAY, ["commons:141534594"])[3]
    with pytest.raises(FscError): w.go(t)
    assert len(F.fetch(w.path, w.cs, t, w.http, S, TODAY, ["commons:141534594"])[0]) == 1
    with pytest.raises(FscError): F.pending(w.cs, S, TODAY, ["nope"])
def test_oversize_stream_stops_early(w):
    t = w.prep()[3]; n = []
    def many():
        for _ in range(50): n.append(1); yield b"z" * (1 << 20)
    class B(httpx.SyncByteStream):
        def __iter__(s): return many()
    orig = w.http.client._transport.handler
    w.http.client._transport.handler = lambda r: R(200, headers={"content-type": "video/webm"}, stream=B()) if r.method == "GET" and r.url.host == "upload.wikimedia.org" else orig(r)
    done, _, errs = w.go(t); assert "exceeds" in errs[0]["error"] and len(n) < 4
def test_extension_refused(w, tmp_path):
    u = "https://upload.wikimedia.org/a/evil.sh"; w.page["imageinfo"][0]["url"] = u; w.cs["candidates"][0]["file_url"] = u
    done, _, errs = w.go(w.prep()[3]); assert not done and "file type" in errs[0]["error"] and w.gets == 0
def test_download_cap(w, monkeypatch):
    monkeypatch.setattr(F, "MAX_DL", 0); done, _, errs = w.go(w.prep()[3]); assert "cap" in errs[0]["error"] and w.gets == 0
