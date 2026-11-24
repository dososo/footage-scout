import datetime as dt, importlib.util, json, pathlib, re, yaml, pytest
from footage_scout import health, gate, cli, providers
from footage_scout.core import FscError, load_sources, read_json, validate
R = pathlib.Path(__file__).resolve().parents[1]
D = dt.date(2026, 11, 23); W = dt.timedelta(7)
def test_weeks_then_retire():
    h = None; seen = []
    for k in range(5): h = health.step(h, False, "x", None, D + k * W); seen.append(health.status("active", h))
    assert seen == ["degraded"] * 3 + ["retired"] * 2; h = health.step(h, True, None, None, D + 5 * W); assert health.status("active", h) == "active" and h["last_ok"]
def test_same_week_counts_once():
    h = health.step(None, False, "x", None, D); h = health.step(h, False, "x", None, D + dt.timedelta(2)); assert h["failures"] == 1; assert health.step(h, True, None, None, D)["failures"] == 0
    h = health.step(h, False, "x", None, D + W); assert h["failures"] == 2 and health.step(h, False, "y", None, D + W)["failures"] == 2
def test_terms_kept_when_unread(): h = health.step(None, True, None, "a" * 64, D); assert health.step(h, False, "x", None, D + W)["terms_sha256"] == "a" * 64
@pytest.mark.parametrize("base", ["blocked", "excluded", "hold", "degraded"])
def test_never_loosens(base): assert health.status(base, dict(failures=0)) == base and health.status(base, dict(failures=9)) == base
def test_overlay():
    s = health.overlay(dict(a=dict(status="active"), b=dict(status="blocked")), dict(sources=dict(a=dict(failures=4), b=dict(failures=0), zz=dict(failures=1)))); assert s["a"]["status"] == "retired" and s["b"]["status"] == "blocked" and "zz" not in s
def test_retired_held(brief):
    from footage_scout import licenses
    s = dict(load_sources()["nps"], status="retired"); assert gate.evaluate(s, licenses.from_source(s), brief, today=dt.date(2026, 11, 24))["verdict"] == "HOLD"
def test_retired_skipped(brief, tmp_path, monkeypatch):
    from footage_scout.core import write_json
    S = dict(load_sources()); S["nps"] = dict(S["nps"], status="retired"); monkeypatch.setattr(cli, "load_sources", lambda: S); write_json(tmp_path/"s.json", brief)
    with pytest.raises(FscError, match="retired"): cli.cmd_search(cli.parser().parse_args(["search", str(tmp_path/"s.json"), "--source", "nps"]), object())
def test_terms_hash(): f = health.terms_hash; assert f("<p>A  b</p><script>1</script>") == f("<div>a b<!-- 2 --></div>") != f("a c")
spec = importlib.util.spec_from_file_location("smoke", R/"scripts/smoke.py"); smoke = importlib.util.module_from_spec(spec)
if (R/"scripts/smoke.py").is_file(): spec.loader.exec_module(smoke)
need = pytest.mark.skipif(not (R/"scripts/smoke.py").is_file(), reason="sdist")
@need
def test_smoke_queries_cover_all(): assert set(smoke.Q) == set(providers.ADAPTERS)
@need
def test_smoke_run(monkeypatch):
    c = dict(asset_id="x:1", gate=dict(verdict="PASS")); n = []
    def probe(http, s):
        n.append(s["id"])
        if s["id"] == "loc": raise FscError("boom | @someone `x`\n# h")
        if s["id"] == "commons": raise FscError("set FSC_CONTACT_URL")
        if s["id"] == "eso": raise FscError("www.eso.org asked us to wait 1179 s")
        return c
    monkeypatch.setattr(smoke, "probe", probe); monkeypatch.setattr(smoke, "terms", lambda h, s: ("b" if s["id"] == "nps" else "a") * 64 if s["id"] in ("nps", "usgs") else None)
    old = dict(schema_version="1.0.0", generated_at="x", sources={i: health.step(None, True, None, "a" * 64, D - W) for i in ("nps", "usgs", "eso")})
    rows, new = smoke.run(None, load_sources(), old, D, pause=lambda s: None); r = {x["id"]: x for x in rows}
    assert r["loc"]["result"] == "fail" and n.count("loc") == 2 and n.count("commons") == 1 and r["commons"]["result"] == "skipped" and "commons" not in new["sources"] and r["nps"]["terms"] == "changed" and r["usgs"]["terms"] == "ok" and r["eso"]["result"] == "skipped" and n.count("eso") == 1 and r["noirlab"]["terms"] == "not_checked" and new["sources"]["eso"]["failures"] == 0 and new["sources"]["eso"]["terms_sha256"] == "a" * 64
    md, bad = smoke.report(rows); assert bad and "`boom / @someone 'x' # h`" in md and "verify_status: stale" in md
    assert smoke.report([dict(id="a", result="ok", error=None, terms="ok", failures=0)])[1] is False and smoke.report([dict(id="a", result="ok", error=None, terms="changed", failures=0)])[1] is True
@need
def test_smoke_terms_only_own_host():
    assert smoke.terms(None, dict(terms_url="https://other.org/t", hosts=["a.org"])) is None and smoke.terms(None, dict(hosts=["a.org"])) is None
wf = sorted((R/".github/workflows").glob("*.yml"))
@pytest.mark.skipif(not wf, reason="sdist")
def test_workflows():
    for f in wf:
        t = f.read_text("utf-8"); y = yaml.safe_load(t); assert y["permissions"] == dict(contents="read") and "pull_request_target" not in t and "--force" not in t
        assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in re.findall(r"uses: (\S+)", t)) and not re.search(r"run:.*\$\{\{ *(github\.event|inputs|needs)", t)
    y = yaml.safe_load((R/".github/workflows/smoke.yml").read_text("utf-8")); assert "permissions" not in y["jobs"]["probe"] and "GH_TOKEN" not in json.dumps(y["jobs"]["probe"]) and y["jobs"]["report"]["permissions"]["issues"] == "write" and "!cancelled()" in y["jobs"]["report"]["steps"][-1]["if"]
@need
@pytest.mark.parametrize("files,ok", [((None, "u"), True), (("gone", "u"), True), ((None, None), False), (("gone", "gone"), False)])
def test_smoke_probe(monkeypatch, files, ok):
    class A:
        def search(s, q, n): return ["nps:0", "nps:1"]
        def resolve(s, i):
            f = files[int(i[-1])]
            if f == "gone": raise FscError("asset not found")
            return dict(asset_id=i, file_url=f, license=None, provenance="x")
    monkeypatch.setattr(smoke.providers, "get", lambda h, s: A()); monkeypatch.setattr(smoke.gate, "evaluate", lambda *a, **k: {}); monkeypatch.setattr(smoke, "validate", lambda n, d: d)
    if ok: assert smoke.probe(None, dict(id="nps"))["file_url"] == "u"
    else:
        with pytest.raises(FscError): smoke.probe(None, dict(id="nps"))
