import json, pytest
from footage_scout import cli, edit, manifest as M
from footage_scout.core import FscError, ProjectLock, file_sha256, read_json, write_json, validate
H = "0" * 64
@pytest.fixture
def proj(tmp_path, manifest):
    p = tmp_path/"media/a.webm"; p.parent.mkdir(); p.write_bytes(b"v"); h = file_sha256(p); a = manifest["assets"][0]; a.update(sha256=h, gate=dict(a["gate"], artifact_sha256=h))
    def save(**k): a.update(k); write_json(tmp_path/M.NAME, manifest); return tmp_path
    save(); return save
def rep(root, changes=None, **k):
    m = read_json(root/M.NAME); i = dict(asset_id="commons:1", sha256=m["assets"][0]["sha256"], changes=changes or [dict(kind="trim", detail="2-7 s")])
    i.update({x: k.pop(x) for x in ("asset_id", "sha256") if x in k}); write_json(root/"edit_report.json", dict(dict(schema_version="1.0.0", brief_sha256=m["brief_sha256"], items=[i] * k.pop("times", 1)), **k)); return root/"edit_report.json"
def lic(m, **k): return dict(read_json(m/M.NAME)["assets"][0]["license"], **k)
def mods(root): return read_json(root/M.NAME)["assets"][0]["modifications"]
def test_plan(proj):
    r = proj(); d = edit.plan(r); c = d["clips"][0]; assert c["path"] == "media/a.webm" and c["rules"] == ["no_ai_edit"] and not d["left_out"] and validate("edit_plan", read_json(r/edit.PLAN))
    proj(license=lic(r, derivatives="no", attribution_required="yes", third_party_rights_flag=True, ai_use="disclose_ai_modification")); assert edit.plan(r)["clips"][0]["rules"] == ["no_edit", "disclose_ai_edit", "credit", "check_third_party"]
@pytest.mark.parametrize("bad", ["hold", "missing", "changed", "hash"])
def test_plan_leaves_out(proj, bad):
    r = proj(); a = read_json(r/M.NAME)["assets"][0]
    if bad == "hold": proj(gate=dict(a["gate"], verdict="HOLD"))
    if bad == "hash": proj(gate=dict(a["gate"], artifact_sha256=H))
    if bad == "missing": (r/"media/a.webm").unlink()
    if bad == "changed": (r/"media/a.webm").write_bytes(b"w")
    d = edit.plan(r); assert d["clips"] == [] and d["left_out"][0]["asset_id"] == "commons:1"
    with pytest.raises(FscError): edit.apply(r, rep(r))
    assert mods(r) == []
def test_apply_idempotent(proj):
    r = proj(); f = rep(r, [dict(kind="trim", detail="2-7 s"), dict(kind="color"), dict(kind="color")]); assert edit.apply(r, f)["updated"][0]["added"] == ["trim: 2-7 s", "color"]; t = (r/M.NAME).read_bytes()
    assert edit.apply(r, f)["updated"][0]["added"] == [] and (r/M.NAME).read_bytes() == t and "trim: 2-7 s; color" in (r/"CREDITS.md").read_text("utf-8")
def test_apply_changes_only_notes(proj):
    r = proj(); a = read_json(r/M.NAME)["assets"][0]; edit.apply(r, rep(r)); b = read_json(r/M.NAME)["assets"][0]; assert dict(b, modifications=[]) == a
@pytest.mark.parametrize("k", [dict(asset_id="x:1"), dict(sha256=H), dict(brief_sha256="1" * 64), dict(times=2), dict(changes=[dict(kind="license")]), dict(changes=[dict(kind="trim", verdict="PASS")]), dict(license="x"), dict(schema_version="2.0.0"), dict(items=[])])
def test_bad_report(proj, k):
    r = proj(); t = (r/M.NAME).read_bytes()
    with pytest.raises(FscError): edit.apply(r, rep(r, **k))
    assert (r/M.NAME).read_bytes() == t and not (r/"CREDITS.md").exists()
def test_all_or_nothing(proj):
    r = proj(); f = rep(r); d = read_json(f); d["items"].append(dict(d["items"][0], asset_id="x:2")); write_json(f, d)
    with pytest.raises(FscError): edit.apply(r, f)
    assert mods(r) == []
@pytest.mark.parametrize("k,kind,ok", [(dict(derivatives="no"), "trim", False), (dict(ai_use="unknown"), "ai_edit", False), (dict(ai_use="no_generative_processing"), "ai_edit", False), (dict(ai_use="disclose_ai_modification"), "ai_edit", True), (dict(ai_use="no_training"), "ai_edit", True), (dict(ai_use="no_generative_processing"), "crop", True)])
def test_licence_limits(proj, k, kind, ok):
    r = proj(); proj(license=lic(r, **k)); f = rep(r, [dict(kind=kind)])
    if ok: edit.apply(r, f); assert mods(r) == [kind]
    else:
        with pytest.raises(FscError, match="licence"): edit.apply(r, f)
def test_hostile_detail(proj):
    r = proj(); edit.apply(r, rep(r, [dict(kind="other", detail="<b>x</b>\n# [a](http://e)‮")])); t = (r/"CREDITS.md").read_text("utf-8"); assert "\n# [a]" not in t and "<b>" not in t and "‮" not in t
def test_cap(proj):
    r = proj(); proj(modifications=[str(i) for i in range(100)])
    with pytest.raises(FscError, match="too many"): edit.apply(r, rep(r))
def test_locked(proj):
    r = proj(); f = rep(r)
    with ProjectLock(r), pytest.raises(FscError, match="locked"): edit.apply(r, f)
def test_cli(proj, capsys):
    r = proj(); assert cli.main(["edit", "plan", str(r), "--json"]) == 0 and json.loads(capsys.readouterr().out)["clips"]; assert cli.main(["edit", "apply", str(r)]) == 1; assert cli.main(["edit", "apply", str(r), "--report", str(rep(r))]) == 0 and mods(r)
