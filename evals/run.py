"""Run evals/briefs.jsonl. Default is offline (schema + routing). --live searches the real sources and checks every verdict
against an oracle written separately from gate.py. Nothing is downloaded.  usage: python evals/run.py [--live] -o OUT_DIR"""
import argparse, datetime as dt, json, pathlib, sys
from types import SimpleNamespace
from footage_scout import cli, core, providers
HERE = pathlib.Path(__file__).parent


def oracle(src, lic, brief, shot, prov):
    """May this be downloaded at all? Independent restatement of the gate rules, allow-list style."""
    if src["gate_default"] != "per_rules" or src["status"] in ("blocked", "excluded", "retired"):
        return False
    if "archive.org" in src["hosts"] and not (src["id"] == "ia" and lic["third_party_rights_flag"] and lic["license_id"].startswith(("CC", "PDM"))):
        return False
    days = (dt.datetime.now(dt.timezone.utc).date() - dt.date.fromisoformat(src["verified_at"])).days
    if src["verify_status"] != "official_read" or not 0 <= days <= 180 or lic["license_id"].lower() in ("unknown", "per_item"):
        return False
    if lic["attribution_required"] not in ("yes", "no") or lic["derivatives"] not in ("yes", "no") or lic["commercial"] not in ("yes", "no"):
        return False
    if shot.get("will_edit", True) and lic["derivatives"] != "yes" or brief["use"] == "commercial" and lic["commercial"] != "yes":
        return False
    if brief["ai"] == "generative" and lic["ai_use"] not in ("allowed", "no_training", "disclose_ai_modification"):
        return False
    if brief.get("dataset_or_training") and lic["ai_use"] in ("no_training", "unknown", "per_item"):
        return False
    if lic["purpose_restriction"] and lic["purpose_restriction"].strip().casefold() != brief.get("purpose", "").strip().casefold():
        return False
    return not (brief.get("documentary") and brief.get("strict_provenance") and prov == "ai_generated")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true")
    p.add_argument("--only")
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args()
    S, out, rows = core.load_sources(), pathlib.Path(a.out), []
    out.mkdir(parents=True, exist_ok=True)
    for line in (HERE / "briefs.jsonl").read_text("utf-8").splitlines():
        e = json.loads(line)
        if a.only and e["id"] != a.only:
            continue
        b = cli.normalise(e["brief"])
        r = dict(id=e["id"], core=e["core"], routed=all(cli.route(s, S) for s in b["shots"]), shots=[])
        if a.live:
            d = out / e["id"]
            core.write_json(d / "shotlist.json", b)
            ns = SimpleNamespace(shotlist=str(d / "shotlist.json"), per_shot=3, per_source=2, source=None, include_degraded=False, all=False, request_log=str(out / "requests.jsonl"))
            try:
                cli.cmd_search(ns)
                cs = core.read_json(d / "candidates.json", "candidate_set")
            except core.FscError as x:
                cs = dict(candidates=[], notices=[str(x)])
            shots = {s["shot_id"]: s for s in b["shots"]}
            r["leaks"] = [c["asset_id"] for c in cs["candidates"] if c["gate"]["verdict"] in ("PASS", "WARN") and not oracle(S[c["source_id"]], c["license"], b, shots[c["shot_id"]], c["provenance"])]
            for s in shots:
                g = [c for c in cs["candidates"] if c["shot_id"] == s]
                ok = [c for c in g if c["gate"]["verdict"] in ("PASS", "WARN") and c["file_url"]]
                r["shots"].append(dict(shot_id=s, candidates=len(g), usable=len(ok), passes=sum(c["gate"]["verdict"] == "PASS" for c in ok), top=[c["asset_id"] for c in ok[:3]]))
            r["notices"] = cs["notices"]
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    sh = [s for r in rows for s in r["shots"]]
    core_sh = [s for r in rows if r["core"] for s in r["shots"]]
    res = dict(schema_version="1.0.0", live=a.live, briefs=len(rows), routed=sum(r["routed"] for r in rows), licence_leaks=sum(len(r.get("leaks", [])) for r in rows),
               shots=len(sh), shots_usable=sum(s["usable"] > 0 for s in sh), core_shots=len(core_sh), core_usable=sum(s["usable"] > 0 for s in core_sh),
               core_with_pass=sum(s["passes"] > 0 for s in core_sh), rows=rows)
    core.write_json(out / "eval_results.json", res)
    print({k: v for k, v in res.items() if k != "rows"})
    return 0 if res["licence_leaks"] == 0 and res["routed"] == res["briefs"] else 1


if __name__ == "__main__":
    sys.exit(main())
