import json, pytest
from footage_scout import cli, gate
def run(capsys, *a):
    rc = cli.main([*a, "--json"]); return rc, json.loads(capsys.readouterr().out)
def test_plan(tmp_path, brief, capsys):
    p = tmp_path/"b.json"; p.write_text(json.dumps(brief)); rc, d = run(capsys, "plan", str(p), "-o", str(tmp_path/"o"))
    assert rc == 0 and d["schema_version"] == "1.0.0" and "commons" in d["routes"]["s1"]
    p.write_text("拍一条森林视频", "utf-8"); assert run(capsys, "plan", str(p))[0] == 1
def test_codes():
    g = lambda *v: [dict(verdict=x) for x in v]
    assert [cli.code(g(*x)) for x in (("PASS","WARN"), ("PASS","HOLD"), ("HOLD","BLOCK"), ())] == [0,2,3,0]
def test_usage_error_is_not_hold():
    with pytest.raises(SystemExit) as e: cli.main(["fetch"])
    assert e.value.code == 1
@pytest.mark.parametrize("c", ["inspect", "mine", "clip", "register", "run"])
def test_commands_need_arguments(c):
    with pytest.raises(SystemExit) as e: cli.main([c])
    assert e.value.code == 1
def test_no_force():
    with pytest.raises(SystemExit): cli.main(["fetch", "x", "--force"])
def test_doctor_env_exit(monkeypatch, capsys):
    monkeypatch.setattr(cli.doctor, "run", lambda: dict(level="none")); assert cli.main(["doctor"]) == 4
def test_sources(capsys): assert run(capsys, "sources", "validate")[1]["count"] == 74
