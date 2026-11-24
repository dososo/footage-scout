import subprocess, pytest
from footage_scout import doctor
@pytest.mark.parametrize("osn,pm,cmd", [("darwin","brew","brew install ffmpeg"),("linux","apt-get","sudo apt install ffmpeg"),
    ("linux","dnf","sudo dnf install ffmpeg"),("windows","winget","winget install Gyan.FFmpeg"),("windows","scoop","scoop install ffmpeg")])
def test_hints_never_run(monkeypatch, osn, pm, cmd):
    def boom(*a, **k): raise AssertionError("process started")
    monkeypatch.setattr(subprocess, "run", boom); monkeypatch.setattr(subprocess, "Popen", boom)
    d = doctor.run(osn, which=lambda c: c if c == pm else None, has=lambda n: False, pyver=(3,12,0))
    h = {c["name"]: c["install_hint"] for c in d["checks"]}; assert h["ffmpeg"] == cmd and d["level"] == "core" and d["executed_install"] is False
def test_only_version_probes(monkeypatch):
    seen = []
    class R: returncode = 0; stdout = "v1\n"; stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda a, **k: (seen.append(a), R)[1])
    doctor.run("darwin", which=lambda c: c, has=lambda n: False)
    assert seen == [["uv","--version"],["ffmpeg","-version"],["ffprobe","-version"]]
def test_old_python(): assert doctor.run("darwin", which=lambda c: None, has=lambda n: False, pyver=(3,10,0))["level"] == "none"
