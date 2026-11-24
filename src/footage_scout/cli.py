import argparse, json, os, pathlib, sys
from . import __version__, credits, doctor, fetch as F, gate, handoff, manifest as M, media, providers, rank, register as reg, score, vision
from .core import FscError, atomic_write, digest, load_sources, read_json, safe_path, validate, write_json
from .http import Http

DEFAULTS = dict(dataset_or_training=False, documentary=False, strict_provenance=False)


def make_http(a):
    base = pathlib.Path(os.environ.get("FSC_CACHE_DIR") or pathlib.Path.home() / ".cache" / "footage-scout")
    base.mkdir(parents=True, exist_ok=True)
    log = None
    if a.request_log:
        fh = open(a.request_log, "a", encoding="utf-8")
        log = lambda d: (fh.write(json.dumps(d) + "\n"), fh.flush())
    return Http(cache=base, log=log)


def code(gs):
    v = {g["verdict"] for g in gs}
    return 3 if "BLOCK" in v else 2 if "HOLD" in v else 0


def normalise(b):
    validate("brief", b)
    ids = [s["shot_id"] for s in b["shots"]]
    if len(ids) != len(set(ids)):
        raise FscError("duplicate shot_id")
    return validate("brief", {**DEFAULTS, **b, "shots": [{"will_edit": True, **s} for s in b["shots"]]})


def route(shot, sources):
    c = [s for s in sources.values() if s["id"] in providers.ADAPTERS]
    t = set(shot["topics"])
    return sorted((s for s in c if t & {*s["topics"]} or "general" in s["topics"]),
                  key=lambda s: (-len(t & {*s["topics"]}), s["gate_default"] != "per_rules", s["source_trust"], s["id"]))[:6]


def cmd_doctor(a):
    d = doctor.run()
    return d, 4 if d["level"] == "none" else 0


def cmd_sources(a):
    s = load_sources()
    return dict(schema_version="1.0.0", valid=True, count=len(s), sources=[
        {k: x[k] for k in ("id", "tier", "status", "gate_default", "verify_status")} for x in s.values()]), 0


def cmd_plan(a):
    raw = sys.stdin.read() if a.brief == "-" else pathlib.Path(a.brief).read_text("utf-8")
    try:
        b = normalise(json.loads(raw))
    except ValueError as e:
        raise FscError("brief is not JSON (natural language is planned by the Skill, not by fsc)") from e
    write_json(pathlib.Path(a.out) / "shotlist.json", b)
    S = load_sources()
    return dict(schema_version="1.0.0", shotlist=str(pathlib.Path(a.out) / "shotlist.json"),
                routes={s["shot_id"]: [x["id"] for x in route(s, S)] for s in b["shots"]}), 0


def cmd_search(a, http=None):
    b, S = normalise(read_json(a.shotlist)), load_sources()
    http, out, notes, good = http or make_http(a), [], [], 0
    for shot in b["shots"]:
        found = {}
        for src in ([S[x] for x in a.source] if a.source else route(shot, S)):
            if src["status"] == "retired":
                notes.append(f"{src['id']}: skipped (retired)")
                continue
            if src["status"] == "degraded" and not a.include_degraded:
                notes.append(f"{src['id']}: skipped (degraded)")
                continue
            try:
                ad = providers.get(http, src)
                ids = []
                for q in shot["queries"]:
                    ids += [i for i in ad.search(q, a.per_source) if i not in ids]
                    if len(ids) >= a.per_source:
                        break
                good += 1
            except FscError as e:
                notes.append(f"{shot['shot_id']}/{src['id']}: {e}")
                continue
            for i in ids[:a.per_source]:
                try:
                    c = dict(ad.resolve(i), shot_id=shot["shot_id"])
                    c["gate"] = gate.gate_candidate(c, b, S)
                    validate("candidate", c)
                    found[c["asset_id"]] = c
                except FscError as e:
                    notes.append(f"{shot['shot_id']}/{i}: {e}")
        cs = rank.rank(list(found.values()), shot, b, S)
        usable = [c for c in cs if c["gate"]["verdict"] in ("PASS", "WARN") and c["file_url"]][:a.per_shot]
        rest = [c for c in cs if c not in usable]
        out += usable + (rest if a.all else rest[:a.per_shot])
        if not usable:
            notes.append(f"{shot['shot_id']}: no downloadable candidate")
    cs = validate("candidate_set", dict(schema_version="1.0.0", brief=b, brief_sha256=digest(b), candidates=out, notices=notes))
    p = pathlib.Path(a.shotlist).parent / "candidates.json"
    write_json(p, cs)
    if not good:
        raise FscError("no source could be searched: " + " | ".join(notes)[:800])
    rows = handoff.write_links(p.parent, b, S)
    return dict(schema_version="1.0.0", candidates=str(p), notices=notes, handoff=rows, items=[
        dict(shot_id=c["shot_id"], asset_id=c["asset_id"], title=c["title"], license=c["license"]["license_id"],
             gate=c["gate"], downloadable=bool(c["file_url"]), score=c["score"], source_page=c["source_page"]) for c in out]), code(c["gate"] for c in out)


def cmd_gate(a):
    cs, S = read_json(a.candidates, "candidate_set"), load_sources()
    b = cs["brief"]
    if a.use: b = dict(b, use=a.use)
    if a.ai: b = dict(b, ai=a.ai)
    r = [dict(shot_id=c["shot_id"], asset_id=c["asset_id"], **gate.gate_candidate(c, b, S)) for c in cs["candidates"]]
    return dict(schema_version="1.0.0", use=b["use"], ai=b["ai"], results=r), code(r)


def cmd_fetch(a, http=None):
    cs, S = read_json(a.candidates, "candidate_set"), load_sources()
    http = http or make_http(a)
    if not a.token:
        todo, held, errs, t = F.prepare(a.candidates, cs, http, S, only=a.only)
        d = dict(schema_version="1.0.0", confirm_token=t if todo and not errs else None, bytes_total=sum(c["bytes_total"] or 0 for c, _ in todo),
                 pending=[dict(asset_id=c["asset_id"], title=c["title"], bytes_total=c["bytes_total"], license=c["license"]["license_id"], gate=g) for c, g in todo])
    else:
        done, held, errs = F.fetch(a.candidates, cs, a.token, http, S, only=a.only)
        d = dict(schema_version="1.0.0", results=done)
    d["not_downloadable"] = [dict(asset_id=c["asset_id"], gate=g) for c, g in held]
    d["errors"] = errs
    return d, code(g for _, g in held) or (1 if errs else 0)


def cmd_credits(a):
    m = read_json(a.manifest, "manifest")
    langs = a.lang.split(",")
    if not set(langs) <= set(credits.L):
        raise FscError("--lang must be zh, en or zh,en")
    root = pathlib.Path(a.manifest).resolve().parent
    missing = [x["asset_id"] for x in m["assets"] if M.existing(root, m, x["asset_id"]) is None]
    p = safe_path(root, "CREDITS.md")
    atomic_write(p, credits.build(m, langs).encode())
    return dict(schema_version="1.0.0", credits=str(p), assets=len(m["assets"]), missing_files=missing,
                not_cleared=[x["asset_id"] for x in m["assets"] if x["gate"]["verdict"] not in ("PASS", "WARN")],
                missing_authors=[x["asset_id"] for x in m["assets"] if not x["tasl"]["author"]]), 0


def cmd_inspect(a, http=None):
    cs = read_json(a.candidates, "candidate_set")
    root = pathlib.Path(a.candidates).resolve().parent
    ids = list(dict.fromkeys(a.only or [c["asset_id"] for c in cs["candidates"]]))[:20]
    known = {c["asset_id"] for c in cs["candidates"]}
    if not set(ids) <= known:
        raise FscError("--only names an asset that is not in the list")
    http, S, items, errs = http or make_http(a), load_sources(), [], []
    for i in ids:
        try:
            items.append(media.inspect(root, i, http, S))
        except FscError as e:
            errs.append(dict(asset_id=i, error=str(e)))
    return dict(schema_version="1.0.0", items=items, errors=errs), 1 if errs else 0


def cmd_mine(a):
    model = None
    if a.query:
        p = pathlib.Path(a.project) / "shotlist.json"
        if not p.is_file():
            raise FscError("ranking by meaning needs shotlist.json in the project: it states whether local AI analysis is allowed")
        vision.allowed(normalise(read_json(p)))
        model = vision.load(a.vision or "clip")
    elif a.vision:
        raise FscError("--vision needs --query")
    return dict(schema_version="1.0.0", **media.mine(a.project, a.asset_id, a.want, a.top, a.threshold, model, a.query)), 0


def cmd_score(a, http=None):
    S = load_sources()
    if a.vision:
        cs = score.by_vision(a.candidates, a.vision, http or make_http(a), S)
    else:
        cs = score.rate(a.candidates, a.rate, S)
    return dict(schema_version="1.0.0", candidates=str(a.candidates), notices=cs["notices"], items=[
        dict(shot_id=c["shot_id"], asset_id=c["asset_id"], title=c["title"], score=c["score"], scorer=c["scorer"], similarity=c.get("similarity"),
             gate=c["gate"], downloadable=bool(c["file_url"])) for c in cs["candidates"]]), 0


def cmd_links(a):
    b, S = normalise(read_json(a.shotlist)), load_sources()
    root = pathlib.Path(a.shotlist).resolve().parent
    rows = handoff.write_links(root, b, S)
    return dict(schema_version="1.0.0", table=str(root / "LINKS.md"), inbox=str(root / "inbox"), links=rows), 0


def cmd_inbox(a, http=None):
    b, S = normalise(read_json(a.shotlist)), load_sources()
    done, left = handoff.scan(pathlib.Path(a.shotlist).resolve().parent, b, S, (lambda: http) if http else lambda: make_http(a))
    return dict(schema_version="1.0.0", registered=done, unpaired=left), code(x["gate"] for x in done) or (1 if left else 0)


def cmd_model(a):
    d = vision.download(a.model) if a.download else vision.status(a.model)
    return dict(schema_version="1.0.0", **d), 0 if d["ready"] else 4


def cmd_edit(a):
    from . import edit
    d = edit.plan(a.project) if a.action == "plan" else edit.apply(a.project, a.report) if a.report else None
    if d is None:
        raise FscError("edit apply needs --report")
    return d, 0


def cmd_clip(a):
    return dict(schema_version="1.0.0", **media.clip(a.project, a.asset_id, a.start, a.end, a.keep_audio)), 0


def cmd_register(a, http=None):
    b, S = normalise(read_json(a.shotlist)), load_sources()
    src = reg.find_source(a.page, S)
    http = http or (make_http(a) if src["id"] in providers.ADAPTERS else None)
    d = reg.register(pathlib.Path(a.shotlist).resolve().parent, b, a.shot, a.page, a.file, S, http, a.title, a.author)
    return dict(schema_version="1.0.0", **d), code([d["gate"]])


def cmd_run(a, http=None):
    """plan -> search -> stills -> pending list. Stops before any download."""
    http = http or make_http(a)
    p, _ = cmd_plan(a)
    a.shotlist = p["shotlist"]
    s, rc = cmd_search(a, http)
    a.candidates, a.token, a.only = s["candidates"], None, [x["asset_id"] for x in s["items"] if x["gate"]["verdict"] in ("PASS", "WARN")] or None
    sheets = cmd_inspect(a, http)[0] if a.only else dict(items=[], errors=[])
    f = cmd_fetch(a, http)[0] if a.only else dict(confirm_token=None, pending=[], errors=[])
    return dict(schema_version="1.0.0", candidates=s["candidates"], routes=p["routes"], handoff=s["handoff"], items=s["items"], sheets=sheets["items"],
                pending=f["pending"], confirm_token=f["confirm_token"], errors=sheets["errors"] + f["errors"], notices=s["notices"]), rc or (1 if f["errors"] else 0)


def cmd_mcp(a):
    try:
        from . import mcp_server
    except ImportError:
        return dict(schema_version="1.0.0", error="MCP support is not installed: reinstall with the mcp extra, footage-scout[mcp]"), 4
    mcp_server.REQUEST_LOG = a.request_log
    mcp_server.main()
    return dict(schema_version="1.0.0"), 0


class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse's default exit 2 would read as HOLD
        self.print_usage(sys.stderr)
        self.exit(1, f"error: {message}\n")


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--request-log")
    p = Parser(prog="fsc")
    p.add_argument("--version", action="version", version=__version__)
    sp = p.add_subparsers(dest="cmd", required=True)
    def add(n, f, *args):
        q = sp.add_parser(n, parents=[common])
        for x in args:
            q.add_argument(*x[0], **x[1])
        q.set_defaults(f=f)
        return q
    A = lambda *n, **k: (n, k)
    pos = lambda v: int(v) if v.isdigit() and 1 <= int(v) <= 20 else parser_err()
    def parser_err(): raise argparse.ArgumentTypeError("1-20")
    add("doctor", cmd_doctor)
    add("sources", cmd_sources, A("action", choices=["validate"]))
    add("plan", cmd_plan, A("brief"), A("-o", "--out", default="footage"))
    add("search", cmd_search, A("shotlist"), A("--per-shot", type=pos, default=3), A("--per-source", type=pos, default=3),
        A("--source", action="append", choices=sorted(providers.ADAPTERS)), A("--include-degraded", action="store_true"), A("--all", action="store_true"))
    add("gate", cmd_gate, A("candidates"), A("--use", choices=["personal_noncommercial", "commercial"]), A("--ai", choices=["none", "local_analysis", "generative"]))
    add("fetch", cmd_fetch, A("candidates"), A("--token"), A("--only", action="append", metavar="ASSET_ID"))
    add("credits", cmd_credits, A("manifest"), A("--lang", default="zh,en"))
    sub = [A("--per-shot", type=pos, default=3), A("--per-source", type=pos, default=3), A("--source", action="append", choices=sorted(providers.ADAPTERS)),
           A("--include-degraded", action="store_true"), A("--all", action="store_true")]
    add("inspect", cmd_inspect, A("candidates"), A("--only", action="append", metavar="ASSET_ID"))
    add("mine", cmd_mine, A("project"), A("asset_id"), A("--want", type=float, default=5.0), A("--top", type=pos, default=5), A("--threshold", type=float, default=0.3),
        A("--query"), A("--vision", choices=sorted(vision.MODELS)))
    q = add("score", cmd_score, A("candidates")).add_mutually_exclusive_group(required=True)
    q.add_argument("--vision", choices=sorted(vision.MODELS))
    q.add_argument("--rate", action="append", nargs=3, metavar=("SHOT", "ASSET_ID", "STARS"))
    add("links", cmd_links, A("shotlist"))
    add("inbox", cmd_inbox, A("shotlist"))
    add("model", cmd_model, A("--model", choices=sorted(vision.MODELS), default="clip"), A("--download", action="store_true"))
    add("clip", cmd_clip, A("project"), A("asset_id"), A("--start", type=float, required=True), A("--end", type=float, required=True), A("--keep-audio", action="store_true"))
    add("edit", cmd_edit, A("action", choices=["plan", "apply"]), A("project"), A("--report"))
    add("register", cmd_register, A("shotlist"), A("--shot", required=True), A("--page", required=True), A("--file", required=True), A("--title"), A("--author"))
    add("run", cmd_run, A("brief"), A("-o", "--out", default="footage"), *sub)
    add("mcp", cmd_mcp)
    return p


def main(argv=None):
    for f in (sys.stdout, sys.stderr):     # a Windows pipe defaults to the ANSI code page, which cannot print most titles
        if hasattr(f, "reconfigure"):
            f.reconfigure(encoding="utf-8")
    a = parser().parse_args(argv)
    try:
        d, rc = a.f(a)
    except (FscError, OSError) as e:
        d, rc = dict(schema_version="1.0.0", error=str(e)), 1
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    elif "error" in d:
        print(f"error: {d['error']}", file=sys.stderr)
    else:
        for k, v in d.items():
            if isinstance(v, list):
                print(f"{k}:")
                for x in v:
                    print("  -", " | ".join(f"{i}={j}" for i, j in x.items()) if isinstance(x, dict) else x)
            elif k != "schema_version":
                print(f"{k}: {v}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
