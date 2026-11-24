import copy, json, pathlib, shutil, subprocess, pytest
from footage_scout import score, vision, rank, media, cli, licenses, gate
from footage_scout.core import FscError, load_sources, write_json, read_json, digest, file_sha256, ProjectLock
from footage_scout import manifest as M
S = load_sources()
def cand(b, i, shot="s1", url="https://images-assets.nasa.gov/a.mp4", **k):
    c = dict(schema_version="1.0.0", asset_id=i, source_id="nasa_images", shot_id=shot, title=k.pop("title", "t"), author=None, source_page="https://images.nasa.gov/x", file_url=url,
             bytes_total=None, tier="T1", provenance="camera", license=licenses.make("CC0-1.0", "no", "yes", "yes"), **k); c["gate"] = gate.gate_candidate(c, b, S); return c
@pytest.fixture
def cs(brief, tmp_path):
    def mk(*cands, **k):
        b = cli.normalise(dict(brief, **k)); d = dict(schema_version="1.0.0", brief=b, brief_sha256=digest(b), candidates=[cand(b, **c) for c in cands], notices=[]); write_json(tmp_path/"candidates.json", d); return tmp_path/"candidates.json"
    return mk
A, B, C = (dict(i=f"nasa_images:{x}") for x in "abc")
def test_rate(cs):
    p = cs(A, dict(B, title="forest")); before = read_json(p); d = score.rate(p, [("s1", A["i"], 5), ("s1", B["i"], "1")], S)
    assert [c["asset_id"] for c in d["candidates"]] == [A["i"], B["i"]] and d["candidates"][0]["relevance"] == 1 and d["candidates"][1]["relevance"] == 0 and {c["scorer"] for c in d["candidates"]} == {"agent"}
    assert read_json(p) == d and d["brief_sha256"] == before["brief_sha256"]
    strip = lambda c: {k: v for k, v in c.items() if k not in ("score", "scorer", "relevance")}
    assert sorted(map(str, map(strip, d["candidates"]))) == sorted(map(str, map(strip, before["candidates"])))
def test_partial_rating_neutral(cs):
    p = cs(A, B, C); d = score.rate(p, [("s1", B["i"], 4), ("s1", C["i"], 2)], S)["candidates"]; assert [c["asset_id"] for c in d] == [B["i"], A["i"], C["i"]] and d[1]["scorer"] == "none" and "relevance" not in d[1]
@pytest.mark.parametrize("r", [[("s1", "nasa_images:a", 0)], [("s1", "nasa_images:a", 6)], [("s1", "nasa_images:a", "4.5")], [("s1", "nasa_images:a", "x")], [("s9", "nasa_images:a", 3)], [("s1", "nope:1", 3)], [], [("s1", "nasa_images:a", 3)] * 2])
def test_bad_ratings(cs, r):
    p = cs(A); t = p.read_bytes()
    with pytest.raises(FscError): score.rate(p, r, S)
    assert p.read_bytes() == t
def test_rate_locked(cs):
    p = cs(A)
    with ProjectLock(p.parent), pytest.raises(FscError, match="locked"): score.rate(p, [("s1", A["i"], 3)], S)
def test_unusable_stay_last(cs):
    p = cs(A, dict(B, url=None)); assert [c["asset_id"] for c in score.rate(p, [("s1", A["i"], 1), ("s1", B["i"], 5)], S)["candidates"]] == [A["i"], B["i"]]
def test_rating_never_changes_gate_or_token(cs):
    from footage_scout import fetch as F
    p = cs(A, B); t = lambda: F.token(read_json(p), sorted(F.pending(read_json(p), S)[0], key=lambda x: x[0]["asset_id"])); a = t(); score.rate(p, [("s1", A["i"], 1)], S); assert t() == a
class Fake:
    scorer = "clip"
    def __init__(s, m): s.m = m; s.seen = []
    def similarity(s, im, texts): s.seen.append((len(im), tuple(texts))); return [s.m[i.getpixel((200, 100))[0] // 64] for i in im]
def sheet(tmp_path, n, val, name):
    from PIL import Image
    p = tmp_path/name; w, h = media.CELL; c = min(3, n); Image.new("RGB", (c*w, -(-n//c)*h), (val, val, val)).save(p, quality=95); return p
@pytest.fixture
def stills(monkeypatch, tmp_path):
    pytest.importorskip("PIL"); vals = {}
    def ins(root, i, http, sources, n=9):
        v = vals[i]
        if v is None: return dict(sheet=None, tiles=0)
        if v == "err": raise FscError("boom")
        return dict(sheet=str(sheet(tmp_path, 2, v, i.split(":")[1] + ".jpg")), tiles=2)
    monkeypatch.setattr(media, "inspect", ins); return vals
def test_vision(cs, stills):
    p = cs(A, B, C, ai="local_analysis"); stills.update({A["i"]: 10, B["i"]: 200, C["i"]: None}); f = Fake({0: .10, 3: .31})
    d = score.by_vision(p, "clip", None, S, f); c = {x["asset_id"]: x for x in d["candidates"]}
    assert d["candidates"][0]["asset_id"] == B["i"] and c[B["i"]]["similarity"] == .31 and c[B["i"]]["relevance"] == 1 and c[A["i"]]["relevance"] == 0 and c[B["i"]]["scorer"] == "clip" and c[C["i"]]["scorer"] == "none"
    assert f.seen[0] == (2, ("forest",)) and any("no image" in n for n in d["notices"]) and not any("weak" in n for n in d["notices"])
def test_vision_weak_and_rerating(cs, stills):
    p = cs(A, B, ai="local_analysis"); stills.update({A["i"]: 10, B["i"]: "err"}); d = score.by_vision(p, "clip", None, S, Fake({0: .1})); assert any("weak match" in n for n in d["notices"]) and any("boom" in n for n in d["notices"]) and d["candidates"][0]["relevance"] == .5
    d = score.rate(p, [("s1", A["i"], 5)], S); a = [c for c in d["candidates"] if c["asset_id"] == A["i"]][0]; assert a["scorer"] == "agent" and "similarity" not in a
def test_vision_needs_consent(cs, stills):
    p = cs(A)
    with pytest.raises(FscError, match="ai=none"): score.by_vision(p, "clip", None, S, Fake({}))
def test_vision_nothing(cs, stills):
    p = cs(A, ai="local_analysis"); stills[A["i"]] = None
    with pytest.raises(FscError, match="no candidate"): score.by_vision(p, "clip", None, S, Fake({}))
def test_vision_cap(cs, stills, monkeypatch):
    monkeypatch.setattr(score, "MAX_VISION", 1); p = cs(dict(B, url=None), A, ai="local_analysis"); stills.update({A["i"]: 10, B["i"]: 200}); d = score.by_vision(p, "clip", None, S, Fake({0: .3, 3: .4})); assert {c["asset_id"]: c["scorer"] for c in d["candidates"]} == {A["i"]: "clip", B["i"]: "none"} and any("only 1 of 2" in n for n in d["notices"])
def test_duplicates_flagged_not_dropped(cs, monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image"); p = cs(A, B, C, ai="local_analysis"); w, h = media.CELL
    import random
    def ins(root, i, *a, **k):
        r = random.Random(1 if i != C["i"] else 2); im = Image.new("L", (9, 8)); im.putdata([r.randrange(256) for _ in range(72)]); q = tmp_path/(i[-1] + ".jpg"); im.resize((w, h), Image.Resampling.BOX if False else Image.Resampling.NEAREST).convert("RGB").save(q, quality=95 if i[-1] == "a" else 60); return dict(sheet=str(q), tiles=1)
    monkeypatch.setattr(media, "inspect", ins); d = score.by_vision(p, "clip", None, S, type("F", (), dict(scorer="siglip", similarity=lambda s, im, t: [.1] * len(im)))())
    assert [n for n in d["notices"] if "duplicate" in n] == ["possible duplicate: nasa_images:a and nasa_images:b"] and len(d["candidates"]) == 3
def test_cells(tmp_path):
    Image = pytest.importorskip("PIL.Image"); w, h = media.CELL; im = Image.new("RGB", (3*w, 2*h))
    for i in range(5): im.paste((40*i + 20,)*3, (i % 3*w, i // 3*h, i % 3*w+w, i//3*h+h))
    im.save(tmp_path/"s.jpg", quality=95); t = vision.cells(tmp_path/"s.jpg", 5); assert len(t) == 5 and all(abs(x.getpixel((w//2, h//2))[0] - (40*i+20)) < 4 for i, x in enumerate(t))
    with pytest.raises(FscError): vision.cells(tmp_path/"s.jpg", 7)
    (tmp_path/"x.jpg").write_bytes(b"GIF89a")
    with pytest.raises(Exception): vision.cells(tmp_path/"x.jpg", 1)
def test_dhash_flat():
    Image = pytest.importorskip("PIL.Image"); assert vision.dhash(Image.new("RGB", (90, 80), (9, 9, 9))) is None
def test_normalise(): assert vision.normalise([1, 3, 2]) == [0, 1, .5] and vision.normalise([2, 2]) == [.5, .5]
def test_rank_mixed_keeps_metadata_out(brief):
    a = dict(asset_id="a", source_id="nasa_images", title="forest"); b = dict(asset_id="b", source_id="nasa_images", title="x", relevance=.75, scorer="agent"); r = rank.rank([a, b], brief["shots"][0], brief, S); assert r[0]["asset_id"] == "b" and r[1]["scorer"] == "none"
@pytest.fixture
def proj(tmp_path, manifest, brief):
    if not shutil.which("ffmpeg"): pytest.skip()
    pytest.importorskip("PIL"); p = tmp_path/"media/a.mp4"; p.parent.mkdir(); subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "smptebars=s=320x180:r=25:d=3", "-f", "lavfi", "-i", "testsrc=s=320x180:r=25:d=5", "-filter_complex", "[0:v]format=yuv420p,setsar=1[a];[1:v]format=yuv420p,setsar=1[b];[a][b]concat=n=2", "-c:v", "mpeg4", "-q:v", "3", str(p)], check=True)
    a = manifest["assets"][0]; h = file_sha256(p); a.update(path="media/a.mp4", sha256=h, gate=dict(a["gate"], artifact_sha256=h)); write_json(tmp_path/M.NAME, manifest); return tmp_path
def test_mine_by_meaning(proj):
    m = type("F", (), dict(scorer="clip", similarity=lambda s, im, t: ([.3, .1] if t == ["bars"] else [.1, .3])))(); base = media.mine(proj, "commons:1", want=2, top=1)
    r = {q: media.mine(proj, "commons:1", want=2, top=1, model=m, query=q) for q in ("bars", "test")}; assert r["bars"]["segments"][0]["in_s"] == 0 and r["test"]["segments"][0]["in_s"] > 2.5 and r["bars"]["scorer"] == "clip" and r["bars"]["segments"][0]["similarity"] == .3 and base["scorer"] == "none"
    for k in (dict(model=m), dict(query="x")):
        with pytest.raises(FscError): media.mine(proj, "commons:1", **k)
def test_mine_consent(proj, brief, monkeypatch):
    a = lambda **k: cli.parser().parse_args(["mine", str(proj), "commons:1", *sum(([f"--{x}", v] for x, v in k.items()), [])])
    with pytest.raises(FscError, match="shotlist"): cli.cmd_mine(a(query="x"))
    write_json(proj/"shotlist.json", brief)
    with pytest.raises(FscError, match="ai=none"): cli.cmd_mine(a(query="x"))
    with pytest.raises(FscError, match="--query"): cli.cmd_mine(a(vision="clip"))
    write_json(proj/"shotlist.json", dict(brief, ai="local_analysis")); seen = []; monkeypatch.setattr(vision, "load", lambda n: (seen.append(n), type("F", (), dict(scorer="clip", similarity=lambda s, im, t: [.1] * len(im)))())[1])
    assert cli.cmd_mine(a(query="x"))[0]["scorer"] == "clip" and seen == ["clip"]
def test_cli_score(cs, capsys):
    p = cs(A); assert cli.main(["score", str(p), "--rate", "s1", A["i"], "4", "--json"]) == 0 and json.loads(capsys.readouterr().out)["items"][0]["scorer"] == "agent"
    with pytest.raises(SystemExit): cli.main(["score", str(p)])
    with pytest.raises(SystemExit): cli.main(["score", str(p), "--vision", "evil"])
def test_shared_slate_is_not_duplicate(cs, monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image"); p = cs(A, B, ai="local_analysis"); w, h = media.CELL
    import random
    def pic(seed): r = random.Random(seed); im = Image.new("L", (9, 8)); im.putdata([r.randrange(256) for _ in range(72)]); return im.resize((w, h), Image.Resampling.NEAREST)
    def ins(root, i, *a, **k):
        im = Image.new("RGB", (3*w, h)); [im.paste(pic(x).convert("RGB"), (n*w, 0)) for n, x in enumerate([1, *((2, 3) if i == A["i"] else (4, 5))])]; q = tmp_path/(i[-1] + ".jpg"); im.save(q, quality=95); return dict(sheet=str(q), tiles=3)
    monkeypatch.setattr(media, "inspect", ins); d = score.by_vision(p, "clip", None, S, Fake({k: .3 for k in range(4)})); assert not [n for n in d["notices"] if "duplicate" in n]
def test_seen_beats_metadata(brief):
    m = dict(duration_s=30, width=3840, height=2160); a = dict(asset_id="a", source_id="esahubble", title="x", relevance=.55, scorer="clip", media=m); b = dict(asset_id="b", source_id="nasa_images", title="x", relevance=1.0, scorer="clip"); assert rank.rank([a, b], brief["shots"][0], brief, S)[0]["asset_id"] == "b"
def test_vision_text_is_description_only(cs, stills, brief):
    p = cs(A, ai="local_analysis", shots=[dict(brief["shots"][0], description="waves breaking on a beach", queries=["waves", "sea"])]); stills[A["i"]] = 10; f = Fake({0: .3}); score.by_vision(p, "clip", None, S, f); assert f.seen == [(2, ("waves breaking on a beach",))]
