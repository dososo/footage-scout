import json, os, subprocess, sys
def test_output_is_utf8_on_a_legacy_code_page(tmp_path, brief):
    """A piped stdout on Windows uses the ANSI code page; titles in any script must still come out, as UTF-8."""
    p = tmp_path/"拍.json"; p.write_text(json.dumps(dict(brief, title="森林")), "utf-8")
    r = subprocess.run([sys.executable, "-m", "footage_scout.cli", "plan", str(p), "-o", str(tmp_path/"输出"), "--json"], capture_output=True, env=dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0"))
    assert r.returncode == 0, r.stderr; assert "输出" in json.loads(r.stdout.decode("utf-8"))["shotlist"]
    r = subprocess.run([sys.executable, "-m", "footage_scout.cli", "plan", str(tmp_path/"没有.json")], capture_output=True, env=dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0"))
    assert r.returncode == 1 and "没有" in r.stderr.decode("utf-8")
