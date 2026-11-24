import os, time, pytest
from footage_scout import manifest as M, core
def test_roundtrip_idempotent(tmp_path, manifest):
    a = manifest["assets"][0]; (tmp_path/"media").mkdir(); f = tmp_path/"media/a.webm"; f.write_bytes(b"x"); a["sha256"] = core.file_sha256(f)
    m = M.put(tmp_path, dict(manifest, assets=[]), a); m = M.put(tmp_path, m, a)
    assert len(m["assets"]) == 1 and M.existing(tmp_path, m, a["asset_id"]) and not list(tmp_path.glob(".tmp*"))
    f.write_bytes(b"y")
    with pytest.raises(core.FscError): M.existing(tmp_path, m, a["asset_id"])
def test_other_brief(tmp_path, manifest):
    M.put(tmp_path, dict(manifest, assets=[]), manifest["assets"][0])
    with pytest.raises(core.FscError): M.load(tmp_path, "p", "1"*64)
def test_tasl_required(tmp_path, manifest):
    manifest["assets"][0]["tasl"].pop("license")
    with pytest.raises(core.FscError): M.put(tmp_path, dict(manifest, assets=[]), manifest["assets"][0])
@pytest.mark.parametrize("p", ["..", "../x", "a/b", "", "a\\b", "a\0"])
def test_traversal(tmp_path, p):
    with pytest.raises(core.FscError): core.safe_path(tmp_path, p)
def test_symlink(tmp_path):
    out = tmp_path/"o"; out.mkdir(); (out/"media").symlink_to(tmp_path)
    with pytest.raises(core.FscError): core.safe_path(out, "media", "x")
    (out/"f").symlink_to(tmp_path/"t")
    with pytest.raises(core.FscError): core.atomic_write(out/"f", b"")
def test_lock(tmp_path):
    with core.ProjectLock(tmp_path):
        with pytest.raises(core.FscError): core.ProjectLock(tmp_path).__enter__()
        os.utime(tmp_path/".fsc.lock", (1, 1))
        with core.ProjectLock(tmp_path): pass
    assert not (tmp_path/".fsc.lock").exists()
def test_symlink_inside_root_also_refused(tmp_path):
    (tmp_path/"real").mkdir(); (tmp_path/"media").symlink_to(tmp_path/"real")
    with pytest.raises(core.FscError): core.safe_path(tmp_path, "media", "x")
