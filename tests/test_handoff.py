import os, pathlib, plistlib, shutil, subprocess, sys, json, pytest
from types import SimpleNamespace as NS
from footage_scout import handoff as H, cli, providers
from footage_scout.core import FscError, load_sources, write_json
S = load_sources()
def b2(brief, **k):
    s = brief["shots"][0]; return cli.normalise(dict(brief, shots=[dict(s, topics=["general"]), dict(s, shot_id="s2", topics=["history_archive"])], **k))
@pytest.fixture(scope="session")
def vid(tmp_path_factory):
    if not shutil.which("ffmpeg"): pytest.skip("ffmpeg")
    p = tmp_path_factory.mktemp("h")/"v.mp4"; subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=2", str(p)], check=True); return p
def put(root, rel, vid, page=None, ext=".txt"):
    p = root/"inbox"/rel; p.parent.mkdir(parents=True, exist_ok=True); shutil.copy(vid, p)
    with open(p, "ab") as f: f.write(rel.encode())        # distinct bytes
    if page: pathlib.Path(str(p)+ext).write_bytes(page if isinstance(page, bytes) else page.encode())
    return p
PAGE = "https://www.pexels.com/video/a-123/"
def test_links(brief):
    r = H.links(b2(brief), S); assert all(S[x["source_id"]]["tier"] in ("T3", "T4") and S[x["source_id"]]["status"] == "active" for x in r)
    from urllib.parse import urlsplit
    assert all(urlsplit(x["url"]).scheme == "https" and urlsplit(x["url"]).hostname in S[x["source_id"]]["hosts"] for x in r)
    assert {x["shot_id"] for x in r} == {"s1", "s2"} and any(x["source_id"] == "mixkit" for x in H.links(b2(brief), S, 9)) and len([x for x in r if x["shot_id"] == "s1"]) == 4
    assert not {x["source_id"] for x in r} & set(providers.ADAPTERS)
@pytest.mark.parametrize("k", list(H.SEARCH))
def test_search_hosts(k):
    from urllib.parse import urlsplit
    assert urlsplit(H.SEARCH[k]).hostname in S[k]["hosts"]
def test_query_is_quoted(brief):
    b = b2(brief); b["shots"][0]["queries"] = ["a/../b?x=1#y&z"]; u = [x["url"] for x in H.links(b, S) if x["source_id"] == "pexels"][0]; assert "a%2F..%2Fb%3Fx%3D1%23y%26z" in u
def test_table_escapes(brief, tmp_path):
    b = b2(brief); b["shots"][0]["description"] = "x | [evil](http://e) <img>\n\n# h"; H.write_links(tmp_path, b, S); t = (tmp_path/"LINKS.md").read_text("utf-8")
    assert "\\| \\[evil\\](http://e) \\<img\\> # h" in t and "\n# h" not in t and (tmp_path/"inbox/s1").is_dir()
    d = json.loads((tmp_path/"links.json").read_text()); assert d["schema_version"] == "1.0.0" and d["links"]
def test_bad_shot_id_makes_no_dir(brief, tmp_path):
    b = b2(brief); b["shots"][0]["shot_id"] = "../evil"; H.write_links(tmp_path/"p", b, S); assert not (tmp_path/"evil").exists() and sorted(x.name for x in (tmp_path/"p/inbox").iterdir()) == ["s2"]
def test_inbox_symlink(brief, tmp_path):
    (tmp_path/"p").mkdir(); (tmp_path/"p/inbox").symlink_to(tmp_path)
    with pytest.raises(FscError): H.write_links(tmp_path/"p", b2(brief), S)
    with pytest.raises(FscError): H.scan(tmp_path/"p", b2(brief), S)
def test_no_inbox(brief, tmp_path):
    with pytest.raises(FscError, match="links"): H.scan(tmp_path, b2(brief), S)
def test_pair_by_folder(brief, tmp_path, vid):
    p = put(tmp_path, "s2/a.mp4", vid, PAGE); n = p.stat().st_size; done, left = H.scan(tmp_path, b2(brief), S)
    assert left == [] and done[0]["shot_id"] == "s2" and done[0]["gate"]["verdict"] == "HOLD" and p.stat().st_size == n
    done, _ = H.scan(tmp_path, b2(brief), S); assert done[0]["status"] == "already_present"
def test_pair_by_prefix_and_unique_source(brief, tmp_path, vid):
    put(tmp_path, "s1-x.mp4", vid, PAGE); put(tmp_path, "y.mp4", vid, "https://www.si.edu/object/1"); put(tmp_path, "z.mp4", vid, "https://www.britishcouncil.org/x")
    done, left = H.scan(tmp_path, b2(brief), S); assert [d["shot_id"] for d in done] == ["s1"] and {x["file"] for x in left} == {"y.mp4", "z.mp4"} and all("page" in x["reason"] or "shot" in x["reason"] for x in left)
def test_unique_source_decides(brief, tmp_path, vid, monkeypatch):
    put(tmp_path, "y.mp4", vid, PAGE); done, _ = H.scan(tmp_path, b2(brief), S); assert done[0]["shot_id"] == "s1"      # pexels is only offered for s1
def test_ambiguous_source(brief, tmp_path, vid):
    b = b2(brief); b["shots"][1]["topics"] = ["general"]; put(tmp_path, "y.mp4", vid, PAGE); done, left = H.scan(tmp_path, b, S); assert not done and "shot unclear" in left[0]["reason"]
def test_unknown_folder(brief, tmp_path, vid):
    put(tmp_path, "nope/a.mp4", vid, PAGE); done, left = H.scan(tmp_path, b2(brief), S); assert not done and "shot unclear" in left[0]["reason"]
def test_single_shot(brief, tmp_path, vid):
    put(tmp_path, "a.mp4", vid, PAGE); assert H.scan(tmp_path, cli.normalise(brief), S)[0][0]["shot_id"] == "s1"
def test_prefix_ambiguity(brief, tmp_path):
    b = b2(brief); b["shots"][1]["shot_id"] = "s1-a"; assert H.shot_for(tmp_path/"s1-a-x.mp4", tmp_path, None, b, [], S) is None and H.shot_for(tmp_path/"s1x.mp4", tmp_path, None, b, [], S) is None
@pytest.mark.parametrize("page", ["https://evil.example/video/1", "http://www.pexels.com/video/1", "https://www.pexels.com/", "https://www.pexels.com", "javascript:alert(1)", "", "https://[bad", "https://videos.pexels.com/x/1.mp4", "file:///etc/passwd"])
def test_bad_pages(brief, tmp_path, vid, page):
    put(tmp_path, "s1/a.mp4", vid, page or b""); done, left = H.scan(tmp_path, b2(brief), S); assert not done and "no known source page" in left[0]["reason"]
@pytest.mark.parametrize("ext,body", [(".txt", "﻿" + PAGE + "\n"), (".url", "[InternetShortcut]\r\nURL=" + PAGE + "\r\n"), (".webloc", plistlib.dumps(dict(URL=PAGE)))])
def test_sidecars(brief, tmp_path, vid, ext, body):
    put(tmp_path, "s1/a.mp4", vid, body, ext); assert len(H.scan(tmp_path, b2(brief), S)[0]) == 1
@pytest.mark.parametrize("ext,body", [(".txt", b"\xff\xfe\xff"), (".url", b"garbage"), (".webloc", b"<plist"), (".webloc", plistlib.dumps([1])), (".txt", PAGE.encode() + b" " * 9000), (".url", b"[InternetShortcut]\nFOO=1")])
def test_broken_sidecars(brief, tmp_path, vid, ext, body):
    put(tmp_path, "s1/a.mp4", vid, body, ext); done, left = H.scan(tmp_path, b2(brief), S); assert not done and left
def test_sidecar_beats_xattr(tmp_path, vid, monkeypatch):
    p = put(tmp_path, "a.mp4", vid, PAGE); monkeypatch.setattr(H, "origin", lambda _: ["https://www.si.edu/x"]); assert H.page_for(p, S) == PAGE
    p = put(tmp_path, "b.mp4", vid, "https://evil.example/x"); assert H.page_for(p, S) is None       # an explicit wrong page is not silently replaced
def test_sidecar_symlink(tmp_path, vid):
    p = put(tmp_path, "a.mp4", vid); t = tmp_path/"t"; t.write_text(PAGE); pathlib.Path(str(p)+".txt").symlink_to(t); assert H.sidecar(p) is None
def test_skips(brief, tmp_path, vid):
    put(tmp_path, "s1/.hidden.mp4", vid, PAGE); put(tmp_path, "s1/a.exe", vid, PAGE); put(tmp_path, "s1/deep/a.mp4", vid, PAGE); (tmp_path/"inbox/s1/l.mp4").symlink_to(vid); (tmp_path/"o").mkdir(); shutil.copy(vid, tmp_path/"o/v.mp4"); (tmp_path/"o/v.mp4.txt").write_text(PAGE); (tmp_path/"inbox/ln").symlink_to(tmp_path/"o")
    assert H.scan(tmp_path, b2(brief), S) == ([], [])
def test_limit(brief, tmp_path, vid, monkeypatch):
    monkeypatch.setattr(H, "MAX_FILES", 1); put(tmp_path, "s1/a.mp4", vid, PAGE); put(tmp_path, "s1/b.mp4", vid, PAGE + "b/"); done, left = H.scan(tmp_path, b2(brief), S); assert len(done) == 1 and "first 1" in left[0]["reason"]
def test_register_error_reported(brief, tmp_path, vid):
    put(tmp_path, "s1/a.mp4", vid, PAGE); put(tmp_path, "s1/b.mp4", vid, PAGE); done, left = H.scan(tmp_path, b2(brief), S); assert len(done) == 1 and "different file" in left[0]["reason"]
def test_adapter_http(brief, tmp_path, vid):
    put(tmp_path, "s1/a.mp4", vid, "https://dareful.com/x/"); seen = []
    def mk(): seen.append(1); raise FscError("net")
    done, left = H.scan(tmp_path, b2(brief), S, mk); assert seen and left[0]["reason"] == "net"
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS attribute")
def test_where_froms(brief, tmp_path, vid):
    p = put(tmp_path, "s1/a.mp4", vid)
    def setx(v): subprocess.run(["xattr", "-wx", "com.apple.metadata:kMDItemWhereFroms", v.hex(), str(p)], check=True)
    setx(plistlib.dumps(["https://videos.pexels.com/1.mp4", PAGE], fmt=plistlib.FMT_BINARY)); assert H.origin(p) == [PAGE, "https://videos.pexels.com/1.mp4"] and H.page_for(p, S) == PAGE
    assert len(H.scan(tmp_path, b2(brief), S)[0]) == 1
    for bad in (b"junk", plistlib.dumps(dict(a=1), fmt=plistlib.FMT_BINARY), plistlib.dumps([1, 2], fmt=plistlib.FMT_BINARY)): setx(bad); assert H.origin(p) == []
def test_zone_identifier(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32"); p = tmp_path/"a.mp4"; pathlib.Path(str(p)+":Zone.Identifier").write_text("[ZoneTransfer]\nZoneId=3\nReferrerUrl="+PAGE+"\nHostUrl=https://x/1.mp4\n"); assert H.origin(p) == [PAGE, "https://x/1.mp4"]
    assert H.origin(tmp_path/"none.mp4") == []
def test_xdg(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux"); monkeypatch.setattr(H, "_xattr", lambda p, n: PAGE.encode() if "referrer" in n else None); assert H.origin(tmp_path) == [PAGE]
def test_cli(brief, tmp_path, vid, capsys):
    write_json(tmp_path/"shotlist.json", b2(brief)); assert cli.main(["links", str(tmp_path/"shotlist.json")]) == 0
    put(tmp_path, "s1/a.mp4", vid, PAGE); assert cli.main(["inbox", str(tmp_path/"shotlist.json"), "--json"]) == 2
    put(tmp_path, "s1/q.mp4", vid); (tmp_path/"inbox/s1/a.mp4").unlink(); assert cli.main(["inbox", str(tmp_path/"shotlist.json")]) == 1
def test_links_skip_inactive(brief):
    s = {"pexels": dict(S["pexels"], status="retired")}; assert H.links(b2(brief), s) == []
