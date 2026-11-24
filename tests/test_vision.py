import hashlib, httpx, pytest
from footage_scout import vision as V, cli, doctor
from footage_scout.core import FscError
R = httpx.Response; BODY = b"w" * 1000
@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("FSC_CACHE_DIR", str(tmp_path)); monkeypatch.setattr(V, "_LOADED", {}); monkeypatch.setitem(V.MODELS, "clip", dict(V.MODELS["clip"], bytes=1000, sha256=hashlib.sha256(BODY).hexdigest())); return tmp_path
def go(h, name="clip"):
    seen = []
    def f(r): seen.append(str(r.url)); return h(r)
    return lambda: V.download(name, httpx.Client(transport=httpx.MockTransport(f))), seen
def test_pins():
    import re
    for m in V.MODELS.values(): assert re.fullmatch("[0-9a-f]{40}", m["revision"]) and re.fullmatch("[0-9a-f]{64}", m["sha256"]) and m["file"].endswith(".safetensors") and m["license"] in ("MIT", "Apache-2.0")
def test_download(env):
    f, seen = go(lambda r: R(302, headers={"location": "https://cas-bridge.xethub.hf.co/x?sig=1"}) if r.url.host == "huggingface.co" else R(200, content=BODY)); s = f(); assert s["weights_present"] and len(seen) == 2 and "/resolve/" + V.MODELS["clip"]["revision"] in seen[0]
    assert f()["weights_present"] and len(seen) == 2 and [p.name for p in V.folder("clip").iterdir()] == ["open_clip_model.safetensors"]
@pytest.mark.parametrize("loc", ["https://evil.example/x", "http://cdn.hf.co/x", "https://hf.co.evil.example/x", "https://evilhf.co/x", "https://u:p@hf.co/x", "https://hf.co:8443/x", "file:///etc/passwd"])
def test_redirects_refused(loc):
    f, seen = go(lambda r: R(302, headers={"location": loc}))
    with pytest.raises(FscError, match="off-list"): f()
    assert len(seen) == 1
def test_redirect_loop():
    f, seen = go(lambda r: R(302, headers={"location": "/again"}))
    with pytest.raises(FscError, match="redirects"): f()
    assert len(seen) == 5
@pytest.mark.parametrize("body", [b"x" * 1000, BODY[:-1], BODY + b"w", b""])
def test_content_mismatch(body):
    f, _ = go(lambda r: R(200, content=body))
    with pytest.raises(FscError): f()
    assert list(V.folder("clip").iterdir()) == [] and not V.status()["weights_present"]
def test_http_error():
    f, _ = go(lambda r: R(403))
    with pytest.raises(FscError, match="403"): f()
def test_symlink(env):
    V.folder("clip").mkdir(parents=True); t = env/"t"; t.write_bytes(BODY); (V.folder("clip")/"open_clip_model.safetensors").symlink_to(t); assert not V.status()["weights_present"]; f, seen = go(lambda r: R(200, content=BODY))
    with pytest.raises(FscError, match="symlink"): f()
def test_corrupt_is_replaced(env):
    V.folder("clip").mkdir(parents=True); p = V.folder("clip")/"open_clip_model.safetensors"; p.write_bytes(b"x" * 1000); f, seen = go(lambda r: R(200, content=BODY)); f(); assert p.read_bytes() == BODY
def test_extra_files(monkeypatch):
    monkeypatch.setitem(V.MODELS, "clip", dict(V.MODELS["clip"], extra={"tokenizer.json": 3})); f, seen = go(lambda r: R(200, content=BODY if r.url.path.endswith("safetensors") else b"abc")); assert f()["weights_present"] and len(seen) == 2
    (V.folder("clip")/"tokenizer.json").unlink(); assert not V.status()["weights_present"]
def test_load_refuses(env, monkeypatch):
    with pytest.raises(FscError, match="one of"): V.load("evil")
    monkeypatch.setattr(V.importlib.util, "find_spec", lambda n: None)
    with pytest.raises(FscError, match="not installed"): V.load("clip")
    monkeypatch.setattr(V.importlib.util, "find_spec", lambda n: 1)
    with pytest.raises(FscError, match="--download"): V.load("clip")
    V.folder("clip").mkdir(parents=True); (V.folder("clip")/"open_clip_model.safetensors").write_bytes(b"x" * 1000)
    with pytest.raises(FscError, match="SHA-256"): V.load("clip")
def test_status_never_downloads(monkeypatch, capsys):
    def boom(*a, **k): raise AssertionError("network")
    monkeypatch.setattr(V.httpx, "Client", boom); assert cli.main(["model"]) == 4 and cli.main(["model", "--json"]) == 4; d = doctor.run("darwin", which=lambda c: c, ver=lambda c: "v", has=lambda n: True); assert d["level"] == "mine" and [c for c in d["checks"] if c["name"] == "clip-weights"][0]["install_hint"].startswith("fsc model --download")
    assert doctor.run("darwin", which=lambda c: c, ver=lambda c: "v", has=lambda n: True, weights=lambda: True)["level"] == "vision"
def test_download_stops_at_size():
    n = []
    def g():
        for i in range(50): n.append(i); yield b"x" * (1 << 20)
    f, _ = go(lambda r: R(200, content=g()))
    with pytest.raises(FscError, match="larger"): f()
    assert len(n) < 4
def test_extra_wrong_size(monkeypatch):
    monkeypatch.setitem(V.MODELS, "clip", dict(V.MODELS["clip"], extra={"tokenizer.json": 3})); f, _ = go(lambda r: R(200, content=BODY if r.url.path.endswith("safetensors") else b"ab"))
    with pytest.raises(FscError, match="pinned"): f()
