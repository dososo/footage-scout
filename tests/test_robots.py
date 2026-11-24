import httpx, pytest
from footage_scout import robots
from footage_scout.core import FscError, load_sources
from helpers import make
S = load_sources(); R = httpx.Response; ISO = S["isorepublic"]; U = "https://isorepublic.com/video/x/"
def ok(txt, path): return robots.allowed(robots.parse(txt), "https://h" + path)
@pytest.mark.parametrize("txt,path,want", [
    ("User-agent: *\nDisallow: *?q=*", "/a?q=1", False), ("User-agent: *\nDisallow: *?q=*", "/a?s=1", True),
    ("User-agent: *\nDisallow: /a\nAllow: /a/b", "/a/b", True), ("User-agent: *\nAllow: /a\nDisallow: /a", "/a", True),
    ("User-agent: *\nDisallow: /*.mp4$", "/x.mp4", False), ("User-agent: *\nDisallow: /*.mp4$", "/x.mp4?a", True),
    ("User-agent: *\nDisallow: /x$", "/x", False), ("User-agent: *\nDisallow: /x$", "/xy", True),
    ("User-agent: *\nDisallow:", "/a", True), ("User-agent: *\nDisallow: /", "/a", False), ("", "/a", True),
    ("User-agent: ClaudeBot\nDisallow: /", "/a", True), ("User-agent: ClaudeBot\nUser-agent: *\nDisallow: /", "/a", False),
    ("User-agent: *\nAllow: /\nUser-agent: Footage-Scout/2\nDisallow: /", "/a", False),
    ("User-agent: footage-scout\nAllow: /\nUser-agent: *\nDisallow: /", "/a", True),
    ("User-agent: *\nDisallow: /a # c\nUser-agent: *\nDisallow: /b", "/a", False), ("User-agent: *\nDisallow: /a\n\nUser-agent: *\nDisallow: /b", "/b", False),
    ("User-agent: *\nDisallow: /%7Ea", "/~a", False), ("User-agent: *\nDisallow: /café", "/caf%c3%a9", False), ("User-agent: *\nDisallow: /", "/robots.txt", True),
    ("﻿User-agent: *\nDisallow: /a*b*c", "/a1b2c3", False), ("User-agent: *\nDisallow: /a*b*c", "/a1c2b3", True), ("User-agent: *\nDisallow: /ab*b$", "/ab", True)])
def test_rules(txt, path, want): assert ok(txt, path) is want
def test_real(fx):
    assert not ok(fx("robots_coverr.co.txt").decode(), "/s?q=forest") and ok(fx("robots_coverr.co.txt").decode(), "/videos/x")
    assert ok(fx("robots_noirlab.edu.txt").decode(), "/public/videos/?search=x") and not ok(fx("robots_noirlab.edu.txt").decode(), "/search/x")
    assert ok(fx("robots_www.eso.org.txt").decode(), "/public/videos/a/") and not ok(fx("robots_www.eso.org.txt").decode(), "/x/confidential/y")
    assert ok(fx("robots_isorepublic.com.txt").decode(), "/?s=a&post_type=video_post") and not ok(fx("robots_dareful.com.txt").decode(), "/wp-admin/x")
def test_hostile_pattern_is_fast():
    import time; t = time.time(); ok("User-agent: *\nDisallow: /" + "*a" * 2000 + "$", "/" + "a" * 4000 + "b"); assert time.time() - t < 1
def w(rb, st=200, hd=None):
    return make(lambda r: R(st, content=rb, headers=hd or {}) if r.url.path == "/robots.txt" else R(200, content=b"page"))
def test_enforced_and_cached():
    h, c, calls = w(b"User-agent: *\nDisallow: /video/")
    for _ in (1, 2):
        with pytest.raises(FscError, match="disallows"): h.get(U, ISO)
    assert [u for _, u in calls] == ["https://isorepublic.com/robots.txt"]
@pytest.mark.parametrize("st", [500, 503, 429])
def test_unavailable_is_closed(st):
    h, c, calls = w(b"", st)
    with pytest.raises(FscError, match="unavailable"): h.get(U, ISO)
    assert len(calls) == 1
@pytest.mark.parametrize("st", [404, 403, 401])
def test_4xx_is_open(st): assert w(b"", st)[0].get(U, ISO) == b"page"
def test_network_error_is_closed():
    def f(r): raise httpx.ConnectError("x")
    with pytest.raises(FscError, match="unavailable"): make(f)[0].get(U, ISO)
def test_redirect_off_allowlist_closed():
    with pytest.raises(FscError, match="allowlist"): w(b"", 302, {"location": "https://evil.example/robots.txt"})[0].get(U, ISO)
def test_redirect_loop_closed():
    with pytest.raises(FscError, match="redirects"): w(b"", 302, {"location": "/robots.txt"})[0].get(U, ISO)
def test_redirect_hop_rechecked():
    h, c, calls = make(lambda r: R(200, content=b"User-agent: *\nDisallow: /no/") if r.url.path == "/robots.txt" else R(302, headers={"location": "/no/x"}))
    with pytest.raises(FscError, match="disallows"): h.get(U, ISO)
    assert not any("/no/" in u for _, u in calls)
def test_crawl_delay_paces():
    h, c, _ = w(b"User-agent: *\nCrawl-delay: 7"); h.get(U, ISO); h.get(U + "2", ISO); assert max(c.slept) == 7
def test_crawl_delay_absurd_refused():
    h, c, _ = w(b"User-agent: *\nCrawl-delay: 9999")
    with pytest.raises(FscError): h.get(U, ISO)
def test_expires(tmp_path):
    h, c, calls = make(lambda r: R(200, content=b""), cache=tmp_path); h.get(U, ISO); c.t += 90000
    h.get(U + "2", ISO); assert sum("robots" in u for _, u in calls) == 2
def test_disk_cache_shared(tmp_path):
    import time
    h, c, calls = make(lambda r: R(200, content=b"User-agent: *\nDisallow: /"), cache=tmp_path); c.t = time.time()
    with pytest.raises(FscError): h.get(U, ISO)
    h2, c2, calls2 = make(lambda r: R(200, content=b""), cache=tmp_path); c2.t = time.time()
    with pytest.raises(FscError, match="disallows"): h2.get(U, ISO)
    assert calls2 == []
def test_cap_drops_partial_rule(monkeypatch):
    monkeypatch.setattr(robots, "CAP", 44); h, *_ = w(b"User-agent: *\nDisallow: /a\nDisallow: /video/zzzzzzzz"); assert h.get(U, ISO) == b"page"
    with pytest.raises(FscError): h.get("https://isorepublic.com/a", ISO)
def test_t1_not_checked():
    h, c, calls = make(lambda r: R(200, content=b"x")); h.get("https://archive.org/x", S["ia"]); assert len(calls) == 1
def test_head_and_media_checked():
    h, c, calls = w(b"User-agent: *\nDisallow: /wp-content/")
    with pytest.raises(FscError, match="disallows"):
        with h.request("HEAD", "https://isorepublic.com/wp-content/uploads/a.mp4", ISO): pass
def test_budget_counts_robots():
    h, c, calls = make(lambda r: R(200, content=b""), budget=1)
    with pytest.raises(FscError, match="budget"): h.get(U, ISO)
