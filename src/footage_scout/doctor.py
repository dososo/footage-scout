"""Detect capabilities. Install commands are only ever displayed."""
import importlib.util, platform, shutil, subprocess, sys
from . import vision
from .core import validate


def _ver(cmd):
    try:
        r = subprocess.run([cmd, "-version" if cmd.startswith("ff") else "--version"], capture_output=True, text=True,
                           timeout=10, stdin=subprocess.DEVNULL)
        return (r.stdout or r.stderr).splitlines()[0][:120] if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def _hint(osname, which, pkg):
    t = {"ffmpeg": {"brew": "brew install ffmpeg", "apt": "sudo apt install ffmpeg", "dnf": "sudo dnf install ffmpeg",
                    "winget": "winget install Gyan.FFmpeg", "scoop": "scoop install ffmpeg"},
         "uv": {"brew": "brew install uv", "apt": "pipx install uv", "dnf": "pipx install uv",
                "winget": "winget install astral-sh.uv", "scoop": "scoop install uv"}}[pkg]
    order = {"darwin": ["brew"], "windows": ["winget", "scoop"]}.get(osname, ["apt", "dnf"])
    for m in order:
        if which("apt-get" if m == "apt" else m):
            return t[m]
    return t[order[0]]


def run(osname=None, which=shutil.which, ver=_ver, has=lambda n: importlib.util.find_spec(n) is not None,
        pyver=None, weights=lambda: vision.status("clip")["weights_present"]):
    osname = osname or platform.system().lower()
    pyver = pyver or sys.version_info[:3]
    checks = []

    def add(name, level, ok, version=None, hint=None):
        checks.append(dict(name=name, level=level, ok=bool(ok), version=version, install_hint=None if ok else hint))

    add("python>=3.11", "core", tuple(pyver) >= (3, 11), ".".join(map(str, pyver)), "uv python install 3.12")
    for c, lvl, pkg in (("uv", "core", "uv"), ("ffmpeg", "media", "ffmpeg"), ("ffprobe", "media", "ffmpeg")):
        v = ver(c) if which(c) else None
        add(c, lvl, v, v, _hint(osname, which, pkg))
    # shot mining uses ffmpeg's own scene filter, so it needs nothing beyond the media level
    add("scene-filter", "mine", all(c["ok"] for c in checks if c["level"] == "media"), None, _hint(osname, which, "ffmpeg"))
    add("mcp", "core", has("mcp"), None, "reinstall with the mcp extra: footage-scout[mcp]")
    for mod in ("open_clip", "torch", "PIL"):
        add(mod, "vision", has(mod), None, "reinstall with the vision extra: footage-scout[vision]")
    add("clip-weights", "vision", weights(), None, f"fsc model --download   (about {vision.MODELS['clip']['bytes'] // 10**6} MB)")
    level = "none"
    for lvl in ("core", "media", "mine", "vision"):
        # uv only distributes the tool and mcp is only needed by `fsc mcp`; the CLI works without both
        if not all(c["ok"] for c in checks if c["level"] == lvl and c["name"] not in ("uv", "mcp")):
            break
        level = lvl
    return validate("doctor", dict(schema_version="1.0.0", os=osname, level=level, browser_handoff=False,
                                   checks=checks, executed_install=False))
