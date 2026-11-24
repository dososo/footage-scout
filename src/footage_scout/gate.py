"""Deterministic licence gate. Pure functions; there is deliberately no override."""
import datetime as dt

ORDER = ("PASS", "WARN", "HOLD", "BLOCK")
UNRESOLVED = ("unknown", "per_item")


def evaluate(source, lic, brief, will_edit=True, provenance="unknown", today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    hits, verdict = [], "PASS"

    def hit(v, rule=None):
        nonlocal verdict
        if rule and rule not in hits:
            hits.append(rule)
        if ORDER.index(v) > ORDER.index(verdict):
            verdict = v

    if source["gate_default"] == "block":
        hit("BLOCK")
    elif source["gate_default"] == "hold":
        hit("HOLD")
    if source.get("status") == "retired":
        hit("HOLD")
    gen, train = brief["ai"] == "generative", brief.get("dataset_or_training", False)
    if lic["derivatives"] == "no" and will_edit:
        hit("BLOCK", "R1")
    if lic["commercial"] == "no" and brief["use"] == "commercial":
        hit("BLOCK", "R2")
    if lic["ai_use"] == "no_generative_processing" and gen:
        hit("BLOCK", "R3")
    if lic["ai_use"] == "no_training" and train:
        hit("BLOCK", "R4")
    age = (today - dt.date.fromisoformat(source["verified_at"])).days
    if (
        lic["license_id"].lower() in UNRESOLVED
        or any(lic[k] in UNRESOLVED for k in ("attribution_required", "commercial", "derivatives"))
        or source["verify_status"] == "stale" or age > 180 or age < 0
        or (lic["ai_use"] in UNRESOLVED and (gen or train))
    ):
        hit("HOLD", "R5")
    if "SA" in lic["license_id"].upper().split("-"):
        hit("WARN", "R6")
    if lic["third_party_rights_flag"]:
        hit("WARN", "R7")
    if brief.get("documentary") and provenance == "ai_generated":
        hit("BLOCK" if brief.get("strict_provenance") else "WARN", "R8")
    pr = lic.get("purpose_restriction")
    if pr and pr.strip().casefold() != brief.get("purpose", "").strip().casefold():
        hit("HOLD", "R9")
    return {"verdict": verdict, "rules": sorted(hits)}


def gate_candidate(cand, brief, sources, today=None):
    src = sources.get(cand["source_id"])
    if src is None:
        return {"verdict": "BLOCK", "rules": ["R5"]}
    shot = next((s for s in brief["shots"] if s["shot_id"] == cand["shot_id"]), None)
    if shot is None:
        return {"verdict": "BLOCK", "rules": []}
    return evaluate(src, cand["license"], brief, shot.get("will_edit", True), cand["provenance"], today)
