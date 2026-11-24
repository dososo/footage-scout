"""Hand-off to an editor and back. The plan lists cleared files; the report says what the edit did to each one.
A report is untrusted input: it can only add change notes to assets that are already cleared, never alter licences or verdicts."""
import pathlib
from . import manifest as M, providers
from .core import FscError, ProjectLock, atomic_write, read_json, safe_path, validate, write_json
from .credits import build

PLAN = "edit_plan.json"
CLEARED = ("PASS", "WARN")


def _verified(root, m, a):
    if a["gate"]["verdict"] not in CLEARED:
        raise FscError(f"{a['asset_id']}: not cleared ({a['gate']['verdict']})")
    if a["gate"].get("artifact_sha256") != a["sha256"] or not M.existing(root, m, a["asset_id"]):
        raise FscError(f"{a['asset_id']}: file missing or not the one that was cleared")


def plan(root):
    """Write edit_plan.json: only cleared assets whose file still matches its hash."""
    root = pathlib.Path(root).resolve()
    m = read_json(safe_path(root, M.NAME), "manifest")
    clips, left = [], []
    for a in m["assets"]:
        try:
            _verified(root, m, a)
        except FscError as e:
            left.append(dict(asset_id=a["asset_id"], reason=str(e)))
            continue
        lic = a["license"]
        rules = []
        if lic["derivatives"] != "yes":
            rules.append("no_edit")
        if lic["ai_use"] not in ("allowed", "no_training", "disclose_ai_modification"):
            rules.append("no_ai_edit")
        if lic["ai_use"] == "disclose_ai_modification":
            rules.append("disclose_ai_edit")
        if lic["attribution_required"] == "yes":
            rules.append("credit")
        if lic["third_party_rights_flag"]:
            rules.append("check_third_party")
        clips.append(dict(asset_id=a["asset_id"], path=a["path"], sha256=a["sha256"], media=a["media"], segment=a["segment"],
                          license_id=lic["license_id"], rules=rules, credit=a["tasl"]["author"] or "missing"))
    d = validate("edit_plan", dict(schema_version="1.0.0", project=m["project"], brief_sha256=m["brief_sha256"], clips=clips, left_out=left))
    p = safe_path(root, PLAN)
    write_json(p, d)
    return dict(schema_version="1.0.0", plan=str(p), clips=clips, left_out=left)


def note(c):
    d = providers.text(c.get("detail"), 160)
    return c["kind"] + (f": {d}" if d else "")


def apply(root, report):
    """All or nothing. Applying the same report twice changes nothing."""
    root = pathlib.Path(root).resolve()
    r = read_json(report, "edit_report")
    with ProjectLock(root):
        m = read_json(safe_path(root, M.NAME), "manifest")
        if r["brief_sha256"] != m["brief_sha256"]:
            raise FscError("edit report belongs to a different brief")
        by, seen, added = {a["asset_id"]: a for a in m["assets"]}, set(), []
        for x in r["items"]:
            i = x["asset_id"]
            a = by.get(i)
            if a is None or i in seen:
                raise FscError(f"edit report: {'duplicate' if i in seen else 'unknown'} asset {i[:80]!r}")
            seen.add(i)
            if x["sha256"] != a["sha256"]:
                raise FscError(f"{i}: the report was made for different content")
            _verified(root, m, a)
            lic, kinds = a["license"], {c["kind"] for c in x["changes"]}
            if kinds and lic["derivatives"] != "yes":
                raise FscError(f"{i}: its licence does not allow edits")
            if "ai_edit" in kinds and lic["ai_use"] not in ("allowed", "no_training", "disclose_ai_modification"):
                raise FscError(f"{i}: its licence does not allow AI edits (ai_use {lic['ai_use']})")
            new = [n for n in dict.fromkeys(note(c) for c in x["changes"]) if n not in a["modifications"]]
            if len(a["modifications"]) + len(new) > 100:
                raise FscError(f"{i}: too many modification notes")
            by[i] = dict(a, modifications=a["modifications"] + new)
            added.append(dict(asset_id=i, added=new))
        m = validate("manifest", dict(m, assets=[by[a["asset_id"]] for a in m["assets"]]))
        write_json(safe_path(root, M.NAME), m)
        p = safe_path(root, "CREDITS.md")
        atomic_write(p, build(m).encode())
    return dict(schema_version="1.0.0", credits=str(p), updated=added)
