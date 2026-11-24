import httpx, pytest
from footage_scout.core import FscError, load_sources
from footage_scout import http as H
from helpers import make
S = load_sources(); IA, COM, LOC, OB = (S[k] for k in ("ia", "commons", "loc", "openbeelden"))
R = httpx.Response
@pytest.mark.parametrize("u", ["http://archive.org/x", "https://evil.org/x", "https://evilus.archive.org/", "https://archive.org.evil.com/", "https://a@archive.org/",
    "https://archive.org:8443/", "https://127.0.0.1/", "https://[::1]/", "file:///etc/passwd", "https://dn1.us.archive.org/x", "https://archive.org\\@evil.com/"])
def test_first_hop_refused(u):
    h, c, calls = make(lambda r: R(200))
    with pytest.raises(FscError): h.get(u, IA)
    assert calls == []
def redir(to):
    return lambda r: R(302, headers={"location": to}) if r.url.host == "archive.org" else R(200, content=b"ok")
def test_ia_redirect_ok():
    h, c, calls = make(redir("https://dn800308.us.archive.org/a.mp4")); assert h.get("https://archive.org/download/a", IA) == b"ok"
@pytest.mark.parametrize("to", ["https://evilus.archive.org/", "http://dn1.us.archive.org/", "https://.us.archive.org/", "https://us.archive.org/", "https://x.us.archive.org.evil.com/", "https://10.0.0.1/", "//evil.com/", "https://u:p@dn1.us.archive.org/"])
def test_bad_redirect(to):
    h, c, calls = make(redir(to))
    with pytest.raises(FscError): h.get("https://archive.org/download/a", IA)
    assert len(calls) == 1
@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.1.1", "169.254.169.254", "198.18.0.4", "::1", "fe80::1%en0", "fd00::1", "::ffff:127.0.0.1"])
def test_private_dns(ip):
    h, c, calls = make(lambda r: R(200), ips=("93.184.216.34", ip))
    with pytest.raises(FscError): h.get("https://archive.org/x", IA)
    assert calls == []
@pytest.mark.parametrize("src,u,gap", [(LOC, "https://www.loc.gov/film-and-videos/?a=", 5), (OB, "https://www.openbeelden.nl/?a=", 10), (COM, "https://commons.wikimedia.org/?a=", 1)])
def test_interval(src, u, gap, tmp_path):
    h, c, _ = make(lambda r: R(200, content=b"x"), cache=tmp_path)
    h.get(u+"1", src); h.get(u+"2", src); assert sum(c.slept) >= gap - 1e-6
    h2, c2, _ = make(lambda r: R(200, content=b"x"), cache=tmp_path); c2.t = c.t; h2.get(u+"3", src); assert sum(c2.slept) >= gap - 1e-6
def test_shared_host_pacing():
    h, c, _ = make(lambda r: R(200)); h.get("https://archive.org/1", IA); h.get("https://archive.org/2", S["ia_nasa"]); assert sum(c.slept) >= .5
def test_retry_after_and_give_up():
    n = []
    h, c, _ = make(lambda r: (n.append(1), R(429, headers={"retry-after": "30"}) if len(n) < 2 else R(200, content=b"k"))[1])
    assert h.get("https://archive.org/x", IA) == b"k" and sum(c.slept) >= 30
    h, c, calls = make(lambda r: R(503))
    with pytest.raises(FscError): h.get("https://archive.org/x", IA)
    assert len(calls) == 4
    h, c, calls = make(lambda r: R(429, headers={"retry-after": "3600"}))
    with pytest.raises(FscError): h.get("https://archive.org/x", IA)
    assert len(calls) == 1 and sum(c.slept) < 60
def test_budget():
    h, c, calls = make(lambda r: R(200), budget=3)
    for i in range(3): h.get(f"https://archive.org/{i}", IA)
    with pytest.raises(FscError): h.get("https://archive.org/9", IA)
def test_cache_24h(tmp_path):
    import os
    h, c, calls = make(lambda r: R(200, content=b"x"), cache=tmp_path); h.get("https://archive.org/x", IA)
    f = next((tmp_path/"http").iterdir()); os.utime(f, (c.t, c.t)); c.t += 86000; h.get("https://archive.org/x", IA); assert len(calls) == 1
    c.t += 500; h.get("https://archive.org/x", IA); assert len(calls) == 2
def test_errors_not_cached(tmp_path):
    h, c, calls = make(lambda r: R(404), cache=tmp_path)
    for _ in range(2):
        with pytest.raises(FscError): h.get("https://archive.org/x", IA)
    assert len(calls) == 2
def test_cap(monkeypatch):
    monkeypatch.setattr(H, "JSON_CAP", 10); h, c, _ = make(lambda r: R(200, content=b"x"*11))
    with pytest.raises(FscError): h.get("https://archive.org/x", IA)
def test_ua():
    assert H.user_agent({}) == "footage-scout/0.5.0" and H.user_agent({"FSC_CONTACT_URL": "https://e.org/a"}).endswith("(+https://e.org/a)")
    assert H.user_agent({"FSC_CONTACT_URL": "https://e.org\r\nX: y"}) == "footage-scout/0.5.0"
def test_commons_needs_contact(monkeypatch):
    monkeypatch.delenv("FSC_CONTACT_URL"); h, c, calls = make(lambda r: R(200))
    with pytest.raises(FscError, match="contact"): h.get("https://commons.wikimedia.org/x", COM)
    assert calls == []
def test_redirect_suffix_not_valid_as_first_hop():
    h, c, calls = make(lambda r: R(200))
    with pytest.raises(FscError):
        with h.request("GET", "https://dn1.us.archive.org/x", IA): pass
    assert calls == []
def test_redirect_loop():
    h, c, calls = make(lambda r: R(302, headers={"location": "https://archive.org/loop"}))
    with pytest.raises(FscError, match="redirect"): h.get("https://archive.org/x", IA)
    assert len(calls) == 6
def test_ia_canadian_node():
    h, _, calls = make(redir("https://dn790000.ca.archive.org/a.mp4")); assert h.get("https://archive.org/download/a", IA) == b"ok"
    for bad in ("https://evilca.archive.org.example/a", "https://xca.archive.org/a"):
        h, *_ = make(redir(bad))
        with pytest.raises(FscError): h.get("https://archive.org/download/a", IA)
def test_slow_page_is_cut(monkeypatch):
    from footage_scout import http as H
    from footage_scout.core import load_sources, FscError
    import httpx
    x, c, calls = make(lambda r: httpx.Response(200, content=iter([b"a"] * 5))); t = [0]; x.clock = lambda: t.__setitem__(0, t[0] + 50) or t[0]
    with pytest.raises(FscError, match="longer"): x.get("https://images-api.nasa.gov/search?q=a", load_sources()["nasa_images"])
