import asyncio, json, shutil, sys, pathlib, pytest
pytest.importorskip("mcp")
from footage_scout import mcp_server as ms, cli
from footage_scout.core import load_sources
from mcp import Client
TOOLS = {"doctor", "plan_shots", "search_footage", "inspect_candidate", "mine_segments", "check_license", "fetch_footage", "register_download", "build_credits"}
@pytest.fixture(autouse=True)
def root(monkeypatch, tmp_path):
    (tmp_path/"w").mkdir(); (tmp_path/"in").mkdir(); monkeypatch.setattr(ms, "ROOT", tmp_path/"w"); monkeypatch.setattr(ms, "INBOX", tmp_path/"in"); return tmp_path
def go(f):
    async def m():
        async with Client(ms.mcp) as c: return await f(c)
    return asyncio.run(m())
def call(n, **a): return go(lambda c: c.call_tool(n, a))
def test_surface():
    ts = go(lambda c: c.list_tools()).tools; assert {t.name for t in ts} == TOOLS
    assert all(t.description and t.annotations and t.annotations.destructive_hint is False and t.input_schema["type"] == "object" for t in ts)
    assert "force" not in json.dumps([t.input_schema for t in ts]).lower()
    ro = {t.name for t in ts if t.annotations.read_only_hint}; assert ro == {"doctor", "check_license"}
    assert {str(r.uri) for r in go(lambda c: c.list_resources()).resources} == {"footage://sources", "footage://manifest"}
    assert [p.name for p in go(lambda c: c.list_prompts()).prompts] == ["footage-brief"]
def test_doctor():
    r = call("doctor"); assert not r.is_error and isinstance(r.structured_content, dict) and r.structured_content["executed_install"] is False and r.content[0].type == "text"
def test_plan_and_errors(brief, root):
    r = call("plan_shots", project="p", brief=brief); assert r.structured_content["exit_code"] == 0 and (root/"w/p/shotlist.json").is_file()
    r = call("plan_shots", project="p", brief=dict(brief, shots=[])); assert r.is_error and "schema" in r.structured_content["error"]
    r = call("search_footage", project="p", sources=["nope"]); assert r.is_error and "searchable" in r.structured_content["error"]
    r = call("check_license", project="p", use="evil"); assert r.is_error
@pytest.mark.parametrize("bad", ["../x", "/etc", "a/b", "", ".hidden", "a\\b", "x" * 80])
def test_project_escape(bad, brief, root):
    try: assert call("plan_shots", project=bad, brief=brief).is_error
    except Exception as e: assert "valid" in str(e).lower() or "pattern" in str(e).lower()
    assert not (root/"x").exists() and list((root/"w").iterdir()) == []
def test_project_symlink(brief, root):
    (root/"w/l").symlink_to(root); assert call("plan_shots", project="l", brief=brief).is_error and not (root/"shotlist.json").exists()
@pytest.mark.parametrize("f", ["../w/x.mp4", "/etc/passwd", "..", "a/../b.mp4"])
def test_inbox_escape(f, brief):
    call("plan_shots", project="p", brief=brief); r = call("register_download", project="p", shot_id="s1", page_url="https://www.pexels.com/video/a/", file=f); assert r.is_error and "unsafe" in r.structured_content["error"]
def test_register(brief, root):
    if not shutil.which("ffmpeg"): pytest.skip()
    import subprocess; subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=3", str(root/"in/a.mp4")], check=True)
    call("plan_shots", project="p", brief=brief); r = call("register_download", project="p", shot_id="s1", page_url="https://www.pexels.com/video/a/", file="a.mp4")
    assert r.structured_content["exit_code"] == 2 and r.structured_content["gate"]["verdict"] == "HOLD"
    c = call("build_credits", project="p").structured_content; assert c["not_cleared"] and "NOT CLEARED" in c["text"]
    r = call("mine_segments", project="p", asset_id=c["not_cleared"][0], want_s=2); assert [x.type for x in r.content] == ["text", "image"] and r.content[1].mime_type == "image/jpeg"
    r = call("mine_segments", project="p", asset_id=c["not_cleared"][0], clip=[0, 1]); assert r.is_error and "cutting" in r.structured_content["error"]
    m = json.loads(go(lambda c: c.read_resource("footage://manifest")).contents[0].text); assert m["projects"]["p"]["assets"]
def test_token_shape_and_gate(brief, root):
    call("plan_shots", project="p", brief=brief); b = cli.normalise(brief); from footage_scout.core import digest, write_json
    write_json(root/"w/p/candidates.json", dict(schema_version="1.0.0", brief=b, brief_sha256=digest(b), candidates=[], notices=[]))
    try: assert call("fetch_footage", project="p", confirm_token="yes").is_error
    except Exception: pass
    r = call("fetch_footage", project="p", confirm_token="0" * 64); assert r.is_error and "token" in r.structured_content["error"]
    assert not call("check_license", project="p", use="commercial", ai="generative").is_error
    for k in (dict(use="evil"), dict(ai="evil")): assert "bad use" in call("check_license", project="p", **k).structured_content["error"]
    r = call("fetch_footage", project="p"); assert r.structured_content["confirm_token"] is None and r.structured_content["pending"] == []
def test_resources_prompt():
    assert len(json.loads(go(lambda c: c.read_resource("footage://sources")).contents[0].text)) == 74
    assert "plan_shots" in go(lambda c: c.get_prompt("footage-brief", {"topic": "森林"})).messages[0].content.text
def test_stdio(tmp_path):
    """The real installed entry point over real stdio: nothing but protocol may reach stdout."""
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def m():
        p = StdioServerParameters(command=sys.executable, args=["-m", "footage_scout.cli", "mcp"], env=dict(__import__("os").environ, FSC_PROJECT_ROOT=str(tmp_path)))
        async with Client(stdio_client(p)) as c:
            return len((await c.list_tools()).tools), (await c.call_tool("doctor", {})).structured_content
    n, d = asyncio.run(m()); assert n == 9 and d["schema_version"] == "1.0.0"
def test_missing_extra(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "footage_scout.mcp_server", None); monkeypatch.delattr("footage_scout.mcp_server", raising=False); assert cli.main(["mcp"]) == 4 and "extra" in capsys.readouterr().err
def test_modes_exclusive(brief):
    call("plan_shots", project="p", brief=brief)
    for k in ({}, dict(vision=True, asset_ids=["a"]), dict(vision=True, ratings=[dict(shot_id="s1", asset_id="a", stars=3)])): assert "exactly one" in call("inspect_candidate", project="p", **k).structured_content["error"]
    for k in (dict(shot_id="s1"), dict(page_url="https://www.pexels.com/video/a/", file="a.mp4")): assert "together" in call("register_download", project="p", **k).structured_content["error"]
def test_ratings(brief, root):
    from test_score import cand; from footage_scout.core import digest, write_json; call("plan_shots", project="p", brief=brief); b = cli.normalise(brief)
    write_json(root/"w/p/candidates.json", dict(schema_version="1.0.0", brief=b, brief_sha256=digest(b), candidates=[cand(b, "nasa_images:a")], notices=[]))
    r = call("inspect_candidate", project="p", ratings=[dict(shot_id="s1", asset_id="nasa_images:a", stars=5)]); assert r.structured_content["items"][0]["scorer"] == "agent"
    assert "ai=none" in call("inspect_candidate", project="p", vision=True).structured_content["error"]
    try: assert call("inspect_candidate", project="p", ratings=[dict(shot_id="s1", asset_id="nasa_images:a", stars=9)]).is_error
    except Exception: pass
def test_inbox_tool(brief, root):
    call("plan_shots", project="p", brief=brief); assert "fsc links" in call("register_download", project="p").structured_content["error"]
    (root/"w/p/inbox").mkdir(); r = call("register_download", project="p"); assert r.structured_content["registered"] == [] and "empty" in r.content[0].text
def test_root_rules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path/"h")); monkeypatch.setenv("USERPROFILE", str(tmp_path/"h")); monkeypatch.delenv("FSC_PROJECT_ROOT", raising=False); d = tmp_path/"plug/sub"; d.mkdir(parents=True); monkeypatch.chdir(d); assert ms._root() == d.resolve()
    (tmp_path/"plug/plugin.json").write_text("{}"); assert ms._root() == (tmp_path/"h/footage-scout").resolve()
    monkeypatch.chdir("/"); assert ms._root().name == "footage-scout"
    monkeypatch.setenv("FSC_PROJECT_ROOT", "${CLAUDE_PROJECT_DIR}"); assert ms._root().name == "footage-scout"
    monkeypatch.setenv("FSC_PROJECT_ROOT", str(tmp_path)); assert ms._root() == tmp_path.resolve()
def test_credits_edit(manifest, root):
    from footage_scout.core import file_sha256, write_json, read_json
    p = root/"w/p"; (p/"media").mkdir(parents=True); f = p/"media/a.webm"; f.write_bytes(b"v"); h = file_sha256(f); a = manifest["assets"][0]; a.update(sha256=h, gate=dict(a["gate"], artifact_sha256=h)); write_json(p/"footage_manifest.json", manifest)
    r = call("build_credits", project="p", edit_plan=True); assert r.structured_content["clips"] and (p/"edit_plan.json").is_file()
    write_json(p/"r.json", dict(schema_version="1.0.0", brief_sha256=manifest["brief_sha256"], items=[dict(asset_id=a["asset_id"], sha256=h, changes=[dict(kind="crop")])]))
    r = call("build_credits", project="p", edit_report="r.json"); assert not r.is_error and "crop" in r.content[0].text and read_json(p/"footage_manifest.json")["assets"][0]["modifications"] == ["crop"]
    (root/"o.json").write_bytes((p/"r.json").read_bytes()); (p/"l.json").symlink_to(root/"o.json"); assert call("build_credits", project="p", edit_report="l.json").is_error
    for bad in ("../o.json", "/etc/a.json", "r.txt"):
        try: assert call("build_credits", project="p", edit_report=bad).is_error
        except Exception as e: assert "pattern" in str(e).lower() or "valid" in str(e).lower()
