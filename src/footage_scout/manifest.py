from .core import FscError, file_sha256, read_json, safe_path, validate, write_json

NAME = "footage_manifest.json"


def load(root, project, brief_sha):
    p = safe_path(root, NAME)
    if not p.exists():
        return {"schema_version": "1.0.0", "project": project, "brief_sha256": brief_sha, "assets": []}
    m = read_json(p, "manifest")
    if m["brief_sha256"] != brief_sha:
        raise FscError("manifest belongs to a different brief; use another output directory")
    return m


def existing(root, m, asset_id):
    """Verified existing asset, or None. Changed content is an error, never silently replaced."""
    for a in m["assets"]:
        if a["asset_id"] == asset_id:
            parts = a["path"].split("/")
            p = safe_path(root, *parts)
            if not p.is_file():
                return None
            if file_sha256(p) != a["sha256"]:
                raise FscError(f"content changed since download: {a['path']}")
            return a
    return None


def put(root, m, asset):
    m = dict(m, assets=[a for a in m["assets"] if a["asset_id"] != asset["asset_id"]] + [asset])
    validate("manifest", m)
    write_json(safe_path(root, NAME), m)
    return m
