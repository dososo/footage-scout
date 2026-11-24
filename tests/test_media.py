import io, json, os, pathlib, shutil, subprocess, httpx, pytest
from footage_scout import media, register as reg, manifest as M, core, cli, licenses, providers
from footage_scout.core import FscError, load_sources, digest, write_json, read_json, file_sha256
from helpers import make
from conftest import TODAY
S = load_sources(); R = httpx.Response
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
def ff(*a): subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True, stdin=subprocess.DEVNULL)
@pytest.fixture(scope="session")
def video(tmp_path_factory):
    p = tmp_path_factory.mktemp("v") / "v.mp4"     # 3 s bars | 2 s black | 4 s test pattern, with audio
    ff("-f", "lavfi", "-i", "smptebars=s=320x180:r=25:d=3", "-f", "lavfi", "-i", "color=black:s=320x180:r=25:d=2", "-f", "lavfi", "-i", "testsrc=s=320x180:r=25:d=4",
       "-f", "lavfi", "-i", "sine=d=9", "-filter_complex", "[0:v]format=yuv420p,setsar=1[a];[1:v]format=yuv420p,setsar=1[b];[2:v]format=yuv420p,setsar=1[c];[a][b][c]concat=n=3[v]", "-map", "[v]", "-map", "3:a", "-c:v", "mpeg4", "-q:v", "3", str(p))
    return p
@pytest.fixture
def proj(tmp_path, manifest, video):
    (tmp_path/"media").mkdir(); shutil.copy(video, tmp_path/"media/a.mp4"); a = manifest["assets"][0]; h = file_sha256(video)
    a.update(path="media/a.mp4", sha256=h, gate=dict(a["gate"], artifact_sha256=h)); write_json(tmp_path/M.NAME, manifest); return tmp_path
def dims(p): m = media.probe(p) or {}; return (m.get("width"), m.get("height"))
def size(p):
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", str(p)], capture_output=True).stdout)["streams"][0]; return d["width"], d["height"]
def test_probe(video): m = media.probe(video); assert m["width"] == 320 and m["fps"] == 25 and abs(m["duration_s"] - 9) < .2
def test_playlist_disguised_refused(tmp_path, video):
    s = tmp_path/"seg.ts"; ff("-i", str(video), "-c:v", "mpeg2video", "-an", "-f", "mpegts", str(s))
    for body in (f"#EXTM3U\n#EXT-X-TARGETDURATION:9\n#EXTINF:9,\n{s}\n#EXT-X-ENDLIST\n", f"ffconcat version 1.0\nfile '{s}'\n", "ffconcat version 1.0\nfile seg.ts\n"):
        p = tmp_path/"x.mp4"; p.write_text(body); assert media.probe(p) is None
        with pytest.raises(FscError): media.frames_sheet(p, [0], tmp_path/"o.jpg")
def test_inspect_local(proj):
    d = media.inspect(proj, "commons:1", None, S); assert d["kind"] == "frames" and len(d["times_s"]) == 9 and size(d["sheet"]) == (1440, 810) and d["media"]["width"] == 320
def img(tmp_path, w, n="p.png"): ff("-f", "lavfi", "-i", f"testsrc=s={w}x100", "-frames:v", "1", str(tmp_path/n)); return (tmp_path/n).read_bytes()
def ia(tmp_path, body):
    files = [dict(name=f"t{i}.jpg", format="Thumbnail") for i in range(4)]
    return make(lambda r: R(200, json=dict(metadata=dict(title="t"), files=files)) if "/metadata/" in r.url.path else R(200, content=body))
def test_inspect_stills(tmp_path):
    h, _, calls = ia(tmp_path, img(tmp_path, 200)); d = media.inspect(tmp_path, "ia:x", h, S); assert d["kind"] == "stills" and size(d["sheet"]) == (1440, 540) and len(calls) == 5
@pytest.mark.parametrize("bad", [b"<svg/>", b"#EXTM3U\n/etc/passwd", b"", b"\xff\xd8\xffgarbage"])
def test_inspect_bad_stills(tmp_path, bad):
    h, *_ = ia(tmp_path, bad); d = media.inspect(tmp_path, "ia:x", h, S); assert d["kind"] == "none" and d["sheet"] is None and d["notices"]
def test_inspect_still_too_big(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MAX_IMG", 50); h, *_ = ia(tmp_path, img(tmp_path, 200)); assert media.inspect(tmp_path, "ia:x", h, S)["kind"] == "none"
def test_inspect_unknown(tmp_path):
    with pytest.raises(FscError): media.inspect(tmp_path, "nope:x", None, S)
def test_mine(proj):
    d = media.mine(proj, "commons:1", want=2, top=5); ss = d["segments"]; assert d["cuts"] == 2 and len(ss) == 2 and d["scorer"] == "none"
    assert abs(ss[0]["out_s"] - 3) < .1 and abs(ss[1]["in_s"] - 5) < .1 and size(d["sheet"])[0] == 960      # black middle dropped
    assert len(media.mine(proj, "commons:1", want=2, top=1)["segments"]) == 1
@pytest.mark.parametrize("k", [dict(want=0), dict(top=0), dict(top=21), dict(threshold=0), dict(threshold=1), dict(want=float("nan"))])
def test_mine_limits(proj, k):
    with pytest.raises(FscError): media.mine(proj, "commons:1", **k)
def test_mine_too_long(proj, monkeypatch):
    monkeypatch.setattr(media, "probe", lambda p: dict(duration_s=10801))
    with pytest.raises(FscError, match="3 h"): media.mine(proj, "commons:1")
def streams(p): return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.split()
def test_clip(proj):
    d = media.clip(proj, "commons:1", 5.2, 7.7); m = read_json(proj/M.NAME, "manifest"); a = m["assets"][1]
    assert d["status"] == "created" and abs(d["media"]["duration_s"] - 2.5) < .1 and streams(proj/d["path"]) == ["video"] and d["media"]["codec"] == "h264"
    assert a["sha256"] == file_sha256(proj/a["path"]) == a["gate"]["artifact_sha256"] and a["segment"] == dict(in_s=5.2, out_s=7.7, parent_sha256=m["assets"][0]["sha256"])
    assert "audio removed" in a["modifications"] and media.clip(proj, "commons:1", 5.2, 7.7)["status"] == "already_present"
    assert "5.2–7.7 s" in __import__("footage_scout.credits").credits.build(m) and not [x for x in proj.iterdir() if x.name.startswith(".")]
    with pytest.raises(FscError, match="already a clip"): media.clip(proj, d["asset_id"], 0, 1)
def test_clip_audio(proj): assert sorted(streams(proj/media.clip(proj, "commons:1", 0, 1, True)["path"])) == ["audio", "video"]
@pytest.mark.parametrize("s,e", [(-1, 2), (2, 2), (3, 2), (0, 99), (0, .05), (float("nan"), 2)])
def test_clip_range(proj, s, e):
    with pytest.raises(FscError, match="inside"): media.clip(proj, "commons:1", s, e)
def edit(proj, f): m = read_json(proj/M.NAME); f(m["assets"][0]); write_json(proj/M.NAME, m)
@pytest.mark.parametrize("f,msg", [(lambda a: a["license"].update(derivatives="no"), "cutting"), (lambda a: a["license"].update(derivatives="unknown"), "cutting"), (lambda a: a["gate"].update(verdict="HOLD"), "cutting"),
    (lambda a: a["gate"].update(artifact_sha256="1"*64), "bind"), (lambda a: a.update(path="../x.mp4"), "unsafe")])
def test_clip_gate(proj, f, msg):
    edit(proj, f)
    with pytest.raises(FscError, match=msg): media.clip(proj, "commons:1", 0, 1)
def test_tampered_file(proj):
    (proj/"media/a.mp4").write_bytes(b"x")
    for f in (lambda: media.clip(proj, "commons:1", 0, 1), lambda: media.inspect(proj, "commons:1", None, S), lambda: media.mine(proj, "commons:1")):
        with pytest.raises(FscError, match="changed"): f()
def test_stale_parent(proj):
    media.clip(proj, "commons:1", 0, 1); m = read_json(proj/M.NAME); m["assets"][1]["segment"]["parent_sha256"] = "2"*64; write_json(proj/M.NAME, m)
    with pytest.raises(FscError, match="older"): media.clip(proj, "commons:1", 0, 1)
def test_missing_tool(proj, monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda n: None)
    with pytest.raises(FscError, match="doctor"): media.mine(proj, "commons:1")
def test_no_manifest(tmp_path):
    with pytest.raises(FscError, match="manifest"): media.mine(tmp_path, "commons:1")
# register
PEX = "https://www.pexels.com/video/forest-123/"
@pytest.fixture
def rg(tmp_path, brief, video):
    f = tmp_path/"dl"/"clip.mp4"; f.parent.mkdir(); shutil.copy(video, f); b = cli.normalise(brief); r = tmp_path/"p"
    return lambda page=PEX, file=f, shot="s1", http=None, **k: reg.register(r, b, shot, page, file, S, http, today=TODAY, **k)
def test_register_hold(rg, tmp_path):
    d = rg(PEX + "?token=secret#x", title="T‮", author="<b>A</b>"); m = read_json(tmp_path/"p"/M.NAME, "manifest"); a = m["assets"][0]
    assert d["gate"]["verdict"] == "HOLD" and a["source_page"] == PEX and "secret" not in json.dumps(m) and a["tasl"]["author"] == "A" and "‮" not in a["tasl"]["title"]
    assert a["sha256"] == file_sha256(tmp_path/"p"/a["path"]) and core.file_sha256(tmp_path/"p/terms"/(a["license"]["terms_snapshot_sha256"] + ".json")) == a["license"]["terms_snapshot_sha256"]
    assert rg()["status"] == "already_present" and (tmp_path/"dl/clip.mp4").is_file() and "NOT CLEARED" in __import__("footage_scout.credits").credits.build(m)
    with pytest.raises(FscError, match="cutting"): media.clip(tmp_path/"p", a["asset_id"], 0, 1)
    assert not [x for x in (tmp_path/"p/media").iterdir() if x.name.startswith(".")]
def test_register_conflict(rg, tmp_path):
    rg(); g = tmp_path/"dl/other.mp4"; ff("-f", "lavfi", "-i", "testsrc=d=1", str(g))
    with pytest.raises(FscError, match="different file"): rg(file=g)
@pytest.mark.parametrize("page", ["https://evil.example/v", "http://www.pexels.com/v", "https://www.pexels.com/", "https://u:p@www.pexels.com/v", "https://www.pexels.com:8443/v", "file:///etc/passwd", "x"])
def test_register_bad_page(rg, page):
    with pytest.raises(FscError): rg(page)
def test_register_bad_files(rg, tmp_path):
    d = tmp_path/"dl"; (d/"l.mp4").symlink_to(d/"clip.mp4"); (d/"e.mp4").write_bytes(b""); (d/"t.mp4").write_text("hello"); (d/"x.txt").write_text("x"); (d/"d.mp4").mkdir()
    if hasattr(os, "mkfifo"): os.mkfifo(d/"f.mp4")     # Windows has no FIFOs
    for n in ("l.mp4", "e.mp4", "t.mp4", "x.txt", "d.mp4", "f.mp4", "none.mp4"):
        with pytest.raises(FscError): rg(file=d/n)
    shutil.copy(d/"clip.mp4", d/"real.txt")
    with pytest.raises(FscError, match="type refused"): rg(file=d/"real.txt")
    with pytest.raises(FscError, match="regular"): rg(file=d/"e.mp4")
    with pytest.raises(FscError, match="shot"): rg(shot="zz")
def test_register_size(rg, monkeypatch):
    monkeypatch.setattr(reg, "MAX_BYTES", 10)
    with pytest.raises(FscError, match="limit"): rg()
def test_register_block(rg):
    b = dict(S["pexels"], gate_default="block"); import footage_scout.register as r
    with pytest.raises(FscError, match="BLOCK"): r.register(pathlib.Path("."), cli.normalise(dict(schema_version="1.0.0", title="t", use="personal_noncommercial", ai="none", orientation="landscape", shots=[dict(shot_id="s1", description="d", queries=["q"], topics=["n"], duration_s=1)])), "s1", PEX, "x.mp4", {"pexels": b}, today=TODAY)
def test_register_live_page(rg, fx, tmp_path):
    h, *_ = make(lambda r: R(404) if r.url.path == "/robots.txt" else R(200, content=fx("t2_dar_item.html")))
    d = rg("https://dareful.com/winter-forest-hike/", http=h, title="liar", author="liar"); a = read_json(tmp_path/"p"/M.NAME)["assets"][0]
    assert d["asset_id"] == "dareful:winter-forest-hike" and d["gate"]["verdict"] == "PASS" and a["tasl"]["author"] == "Dareful" and a["tasl"]["title"] == "Winter Forest Hike"
def test_cli_inspect_run(tmp_path, brief, fx, monkeypatch, capsys):
    b = tmp_path/"b.json"; b.write_text(json.dumps(brief)); o = tmp_path/"o"
    png = img(tmp_path, 200)
    def h(r):
        if r.url.path == "/robots.txt": return R(404)
        if r.method == "HEAD": return R(200, headers={"content-length": "5"})
        if r.url.path.endswith((".jpg", ".png")): return R(200, content=png)
        return R(200, content=fx("t2_iso_search.html")) if r.url.query else R(200, text=fx("t2_iso_item.html").decode().replace("<strong>Coverr</strong>", "<strong>ISO Republic</strong>"))
    x, _, calls = make(h); monkeypatch.setattr(cli, "make_http", lambda a: x)
    import datetime; monkeypatch.setattr(cli.gate.dt, "datetime", type("D", (datetime.datetime,), {"now": classmethod(lambda c, tz=None: datetime.datetime(2026, 11, 24, tzinfo=tz))}))
    rc = cli.main(["run", str(b), "-o", str(o), "--source", "isorepublic", "--json"]); d = json.loads(capsys.readouterr().out)
    assert rc == 0 and d["confirm_token"] and len(d["pending"]) == 3 and d["sheets"][0]["kind"] == "stills" and not (o/"media").exists() and not any(m == "GET" and u.endswith(".mp4") for m, u in calls)
    assert cli.main(["inspect", str(o/"candidates.json"), "--only", "zz:1"]) == 1; capsys.readouterr()
def test_cli_mine_clip_register(proj, capsys, tmp_path, brief, video):
    assert cli.main(["mine", str(proj), "commons:1", "--json"]) == 0 and json.loads(capsys.readouterr().out)["segments"]
    assert cli.main(["clip", str(proj), "commons:1", "--start", "0", "--end", "1", "--json"]) == 0; capsys.readouterr()
    q = tmp_path/"q"; q.mkdir(); (q/"shotlist.json").write_text(json.dumps(brief))
    assert cli.main(["register", str(q/"shotlist.json"), "--shot", "s1", "--page", PEX, "--file", str(video), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "registered"
    assert cli.main(["credits", str(q/M.NAME), "--json"]) == 0 and json.loads(capsys.readouterr().out)["not_cleared"]
def test_dissolve_found(proj, tmp_path):
    v = tmp_path/"x.mp4"; ff("-f", "lavfi", "-i", "smptebars=s=320x180:r=25:d=5", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=5", "-filter_complex", "[0:v][1:v]xfade=duration=1.5:offset=3.5", "-c:v", "mpeg4", "-q:v", "3", str(v))
    shutil.copy(v, proj/"media/a.mp4"); h = file_sha256(v); edit(proj, lambda a: (a.update(sha256=h), a["gate"].update(artifact_sha256=h)))
    d = media.mine(proj, "commons:1", want=2); ss = d["segments"]; assert d["cuts"] == 0 and d["dissolves"] == 1 and len(ss) == 2 and 3 <= ss[0]["out_s"] <= 4 and 4.4 <= ss[1]["in_s"] <= 5.6
def test_clusters(): assert media._clusters([8, 11.5, 12, 13, 20]) == [(7.5, 8.5), (11, 13.5), (19.5, 20.5)]
def test_long_take_split(proj, monkeypatch):
    monkeypatch.setattr(media, "_changes", lambda *a: []); monkeypatch.setattr(media, "probe", lambda p: dict(duration_s=90.0)); monkeypatch.setattr(media, "frames_sheet", lambda *a: None); assert media.mine(proj, "commons:1", want=2)["shots"] == 4
def test_lock_kept_alive(tmp_path):
    import time
    with core.ProjectLock(tmp_path, ttl=.3) as lk:
        with lk.alive(every=.05):
            time.sleep(.6)
            with pytest.raises(FscError, match="locked"): core.ProjectLock(tmp_path, ttl=.3).__enter__()
        (tmp_path/".fsc.lock").write_text("stolen")
        with pytest.raises(FscError, match="lost"):
            with lk.alive(): pass
    assert (tmp_path/".fsc.lock").exists()
def test_clip_uses_lock(proj):
    with core.ProjectLock(proj):
        with pytest.raises(FscError, match="locked"): media.clip(proj, "commons:1", 0, 1)
def test_clip_lock_lost_not_recorded(proj, monkeypatch):
    real = media.probe
    def f(p):
        if "part-" in str(p): (proj/".fsc.lock").write_text("other")
        return real(p)
    monkeypatch.setattr(media, "probe", f)
    with pytest.raises(FscError, match="lost"): media.clip(proj, "commons:1", 0, 1)
    assert len(read_json(proj/M.NAME)["assets"]) == 1
def test_clip_duration_check(proj, monkeypatch):
    real = media.probe; monkeypatch.setattr(media, "probe", lambda p: dict(real(p), duration_s=99.) if "part-" in str(p) else real(p))
    with pytest.raises(FscError, match="duration"): media.clip(proj, "commons:1", 0, 1)
    assert not list((proj/"clips").iterdir())
def test_lock_released_after_register(rg, tmp_path): rg(); assert not (tmp_path/"p/.fsc.lock").exists()
