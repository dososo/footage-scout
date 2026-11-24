"""Local media work through ffmpeg. Inputs are untrusted files: only the file protocol and real container demuxers are
allowed, so a playlist renamed to .mp4 cannot make ffmpeg open other files or the network."""
import contextlib, datetime as dt, json, pathlib, re, shutil, subprocess, tempfile
from . import manifest as M
from .core import FscError, ProjectLock, atomic_write, digest, file_sha256, safe_path

SAFE = ["-protocol_whitelist", "file", "-format_whitelist", "mov,matroska,webm,ogg,mpeg,mpegts,mpegvideo"]
CELL, MAX_IMG = (480, 270), 8 << 20
FIT = f"scale={CELL[0]}:{CELL[1]}:force_original_aspect_ratio=decrease,pad={CELL[0]}:{CELL[1]}:(ow-iw)/2:(oh-ih)/2,setsar=1"


def _run(cmd, timeout=300):
    if not shutil.which(cmd[0]):
        raise FscError(f"{cmd[0]} is not installed; run `fsc doctor`")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise FscError(f"{cmd[0]} timed out after {timeout} s") from e
    if r.returncode:
        raise FscError(f"{cmd[0]} failed: {r.stderr.decode('utf-8', 'replace').strip()[-200:]}")
    return r


def _in(p): return ["-i", "file:" + str(pathlib.Path(p).resolve())]


FF = ["ffmpeg", "-v", "error", "-nostdin", "-y"]


def probe(p):
    """None when ffprobe is missing or the file has no readable video stream."""
    try:
        r = _run(["ffprobe", "-v", "error", *SAFE, "-select_streams", "v:0", "-show_entries",
                  "stream=width,height,codec_name,avg_frame_rate:format=duration", "-of", "json", *_in(p)], 60)
        d = json.loads(r.stdout)
        s = d["streams"][0]
        n, _, q = s["avg_frame_rate"].partition("/")
        m = dict(duration_s=float(d["format"]["duration"]), width=s["width"], height=s["height"], codec=s["codec_name"])
        if float(q or 1) and float(n):
            m["fps"] = round(float(n) / float(q or 1), 3)
        return m if m["duration_s"] > 0 else None
    except (FscError, ValueError, KeyError, IndexError, TypeError):
        return None


def _tile(imgs, out):
    """imgs: existing image files -> one JPEG contact sheet (row-major)."""
    cols = min(3, len(imgs))
    with tempfile.TemporaryDirectory() as d:
        for i, p in enumerate(imgs):
            _run([*FF, "-protocol_whitelist", "file", "-f", "image2", "-pattern_type", "none", *_in(p), "-frames:v", "1", "-vf", FIT, f"{d}/{i:03d}.png"], 60)
        _run([*FF, "-f", "image2", "-i", f"{d}/%03d.png", "-vf", f"tile={cols}x{-(-len(imgs) // cols)}", "-frames:v", "1", "-q:v", "4", f"{d}/o.jpg"], 60)
        atomic_write(out, pathlib.Path(d, "o.jpg").read_bytes())
    return out


def _frame(p, t, out, vf):
    _run([*FF, *SAFE, "-ss", f"{t:.3f}", *_in(p), "-map", "0:v:0", "-frames:v", "1", "-vf", vf, out], 120)
    return pathlib.Path(out).is_file() and pathlib.Path(out).stat().st_size > 0


def frames_sheet(p, times, out):
    with tempfile.TemporaryDirectory() as d:
        got = [(t, f"{d}/{i}.png") for i, t in enumerate(times) if _frame(p, t, f"{d}/{i}.png", FIT)]
        if not got:
            raise FscError("no frame could be decoded")
        _tile([x for _, x in got], out)
        return [round(t, 3) for t, _ in got]


def _sheet_path(root, key):
    safe_path(root, "sheets").mkdir(exist_ok=True)
    return safe_path(root, "sheets", digest(key)[:24] + ".jpg")


def local(root, asset_id):
    """(asset record, verified path) for a downloaded asset; the gate record must still bind these exact bytes."""
    p = safe_path(root, M.NAME)
    if not p.is_file():
        raise FscError("no manifest here; fetch or register first")
    m = M.read_json(p, "manifest")
    a = M.existing(root, m, asset_id)
    if not a:
        raise FscError(f"not downloaded: {asset_id}")
    if a["gate"]["artifact_sha256"] != a["sha256"]:
        raise FscError("gate record does not bind this file")
    return m, a, safe_path(root, *a["path"].split("/"))


def sniff(b):
    return b[:3] == b"\xff\xd8\xff" or b[:8] == b"\x89PNG\r\n\x1a\n" or b[:4] == b"RIFF" and b[8:12] == b"WEBP"


def inspect(root, asset_id, http, sources, n=9):
    """Contact sheet: real frames when downloaded, otherwise the source's own still images (video is never streamed)."""
    from . import providers
    try:
        _, a, p = local(root, asset_id)
    except FscError as e:
        if not str(e).startswith(("no manifest", "not downloaded")):
            raise
        a = None
    if a:
        med = probe(p)
        if not med:
            raise FscError("ffprobe cannot read this file; run `fsc doctor`")
        times = [med["duration_s"] * (i + 0.5) / n for i in range(n)]
        out = _sheet_path(root, [asset_id, a["sha256"], n])
        return dict(asset_id=asset_id, kind="frames", sheet=str(out), times_s=(got := frames_sheet(p, times, out)), tiles=len(got), media=med, notices=[])
    src = sources.get(asset_id.split(":")[0])
    if not src:
        raise FscError(f"unknown source in asset id: {asset_id[:60]!r}")
    urls, notes = providers.get(http, src).previews(asset_id), []
    with tempfile.TemporaryDirectory() as d:
        imgs = []
        for i, u in enumerate(urls[:n]):
            try:
                b = http.get(u, src, cap=MAX_IMG)
                if not sniff(b):
                    raise FscError("preview is not JPEG, PNG or WebP")
                f = pathlib.Path(d, f"{i}.img")
                f.write_bytes(b)
                _run([*FF, "-protocol_whitelist", "file", "-format_whitelist", "image2,jpeg_pipe,png_pipe,webp_pipe", *_in(f), "-frames:v", "1", "-vf", FIT, f"{d}/{i}.png"], 60)
                imgs.append(f"{d}/{i}.png")
            except FscError as e:
                notes.append(str(e))
        out = _tile(imgs, _sheet_path(root, [asset_id, urls])) if imgs else None
    if not out:
        notes.append("the source publishes no usable still image")
    return dict(asset_id=asset_id, kind="stills" if out else "none", sheet=str(out) if out else None, times_s=[], tiles=len(imgs), media=None, notices=notes)


SOFT_FPS, SOFT = 2, 0.12


def _changes(p, pre, t):
    r = _run(["ffmpeg", "-v", "error", "-nostdin", *SAFE, *_in(p), "-map", "0:v:0", "-vf",
              f"{pre}scale=160:-2,select='gt(scene,{t})',metadata=print:file=-", "-f", "null", "-"], 1800)
    return [float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stdout.decode("utf-8", "replace"))]


def _clusters(ts):
    """Frame-to-frame scores miss dissolves; differences between samples 1/SOFT_FPS apart see them. A run of close samples is one
    transition: the shot before it ends at its start and the next shot begins at its end."""
    out = []
    for t in ts:
        if out and t - out[-1][1] <= 1.0:
            out[-1][1] = t
        else:
            out.append([t - 1 / SOFT_FPS, t])
    return [(a, b + 1 / SOFT_FPS) for a, b in out]


def mine(root, asset_id, want=5.0, top=5, threshold=0.3, model=None, query=None):
    """Cut a downloaded long clip into shots. Ranking is technical (length fit, contrast) unless a vision model and a query are given."""
    if bool(model) != bool(query):
        raise FscError("ranking by meaning needs both a query and a vision model")
    if not 0 < want <= 600 or not 1 <= top <= 20 or not 0.05 <= threshold <= 0.95:
        raise FscError("want 0-600 s, top 1-20, threshold 0.05-0.95")
    _, a, p = local(root, asset_id)
    med = probe(p)
    if not med:
        raise FscError("ffprobe cannot read this file; run `fsc doctor`")
    if med["duration_s"] > 10800:
        raise FscError("longer than 3 h; clip a part first")
    hard = [(c, c) for c in _changes(p, "", threshold)]
    spans = hard + [x for x in _clusters(_changes(p, f"fps={SOFT_FPS},", SOFT)) if not any(x[0] - 0.1 <= c <= x[1] + 0.1 for c, _ in hard)]
    segs, at = [], 0.0
    for a0, b0 in sorted(x for x in spans if 0 < x[0] < med["duration_s"]) + [(med["duration_s"],) * 2]:
        k = max(1, int((a0 - at) // 30) + 1) if a0 - at > 60 else 1     # unbroken takes are offered in pieces
        segs += [(at + (a0 - at) * i / k, at + (a0 - at) * (i + 1) / k) for i in range(k)]
        at = max(at, b0)
    segs = [x for x in segs if x[1] - x[0] >= 1.0]
    segs = sorted(sorted(segs, key=lambda x: -min(want, x[1] - x[0]))[:80])
    good = []
    for s, e in segs:
        v = _run([*FF, *SAFE, "-ss", f"{(s + e) / 2:.3f}", *_in(p), "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=32:18,format=gray",
                  "-f", "rawvideo", "-"], 120).stdout
        if len(v) != 576:
            continue
        mean = sum(v) / 576
        std = (sum((x - mean) ** 2 for x in v) / 576) ** 0.5
        if mean < 12 or std < 4:     # black, or flat title / fade frames
            continue
        good.append(dict(in_s=round(s, 3), out_s=round(e, 3), score=round(0.6 * min(1, (e - s) / want) + 0.4 * min(1, std / 50), 4)))
    if model and good:
        from . import vision
        tiles = []
        for k in range(0, len(good), 9):
            part = good[k:k + 9]
            with tempfile.TemporaryDirectory() as d:
                got = frames_sheet(p, [(x["in_s"] + x["out_s"]) / 2 for x in part], pathlib.Path(d, "s.jpg"))
                if len(got) != len(part):
                    raise FscError("a frame could not be decoded for scoring")
                tiles += vision.cells(f"{d}/s.jpg", len(got))
        sims = model.similarity(tiles, [query])
        for x, s, r in zip(good, sims, vision.normalise(sims)):
            x.update(similarity=round(s, 4), score=round(0.7 * r + 0.3 * x["score"], 4))
    best = sorted(sorted(good, key=lambda x: (-x["score"], x["in_s"]))[:top], key=lambda x: x["in_s"])
    out = None
    if best:
        out = _sheet_path(root, [asset_id, a["sha256"], best])
        frames_sheet(p, [(x["in_s"] + x["out_s"]) / 2 for x in best], out)
    return dict(asset_id=asset_id, duration_s=med["duration_s"], cuts=len(hard), dissolves=len(spans) - len(hard), shots=len(segs), segments=best, sheet=str(out) if out else None, scorer=model.scorer if model else "none")


def clip(root, asset_id, start, end, keep_audio=False):
    """Frame-accurate H.264 cut, silent unless asked. Cutting is an adaptation, so the licence must allow derivatives."""
    root = pathlib.Path(root).resolve()
    with ProjectLock(root) as lk:
        m, a, p = local(root, asset_id)
        if a["segment"]:
            raise FscError("this asset is already a clip; cut from the original")
        if a["gate"]["verdict"] not in ("PASS", "WARN") or a["license"]["derivatives"] != "yes":
            raise FscError("licence does not clear cutting this asset")
        med = probe(p)
        if not med:
            raise FscError("ffprobe cannot read this file; run `fsc doctor`")
        if not 0 <= start < end <= med["duration_s"] + 0.05 or end - start < 0.1:
            raise FscError(f"clip must lie inside 0-{med['duration_s']:.2f} s and last at least 0.1 s")
        start, end = round(start, 3), round(min(end, med["duration_s"]), 3)
        cid = f"{asset_id}#t={start:g},{end:g}" + (",audio" if keep_audio else "")
        old = M.existing(root, m, cid)
        if old:
            if old["segment"]["parent_sha256"] != a["sha256"]:
                raise FscError("clip belongs to an older copy of the source file")
            return dict(asset_id=cid, path=old["path"], sha256=old["sha256"], media=old["media"], status="already_present")
        enc = _run(["ffmpeg", "-hide_banner", "-encoders"], 30).stdout.decode("utf-8", "replace")
        codec = next((c for c in ("libx264", "h264_videotoolbox", "libopenh264") if re.search(rf"\b{c}\b", enc)), None)
        if not codec:
            raise FscError("this ffmpeg has no H.264 encoder; run `fsc doctor`")
        safe_path(root, "clips").mkdir(exist_ok=True)
        dest = safe_path(root, "clips", f"{a['source_id']}_{digest(cid)[:16]}.mp4")
        with tempfile.TemporaryDirectory(dir=root, prefix=".part-") as d, lk.alive():
            t = f"{d}/c.mp4"
            _run([*FF, *SAFE, "-ss", f"{start:.3f}", *_in(p), "-t", f"{end - start:.3f}", "-map", "0:v:0", *(["-map", "0:a:0?", "-c:a", "aac"] if keep_audio else ["-an"]),
                  "-map_metadata", "-1", "-c:v", codec, *(["-crf", "17", "-preset", "medium"] if codec == "libx264" else ["-b:v", "20M"]),
                  "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p", "-movflags", "+faststart", t], 1800)
            got = probe(t)
            if not got or abs(got["duration_s"] - (end - start)) > max(0.25, 3 / got.get("fps", 24)):
                raise FscError("clip duration check failed")
            sha = file_sha256(t)
            pathlib.Path(t).replace(dest)
        mods = ["re-encoded to H.264"] + ([] if keep_audio else ["audio removed"])
        M.put(root, m, dict(a, asset_id=cid, path=f"clips/{dest.name}", sha256=sha, gate=dict(a["gate"], artifact_sha256=sha), media=got,
                            segment=dict(in_s=start, out_s=end, parent_sha256=a["sha256"]), modifications=a["modifications"] + mods))
    return dict(asset_id=cid, path=f"clips/{dest.name}", sha256=sha, media=got, status="created")
