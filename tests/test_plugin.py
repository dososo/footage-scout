import json, pathlib, re, sys, yaml, pytest
from footage_scout import cli, core, providers, __version__
R = pathlib.Path(__file__).parents[1]; P = R; K = R/"skills/footage-scout"
pytestmark = pytest.mark.skipif(not K.is_dir(), reason="plugin not shipped in this archive")
J = lambda p: json.loads(p.read_text("utf-8"))
def fm(): t = (K/"SKILL.md").read_text("utf-8"); return yaml.safe_load(t.split("---")[1]), t
def test_frontmatter():
    m, t = fm(); assert m["name"] == K.name and 1 <= len(m["description"]) <= 1024 and len(m["compatibility"]) <= 500 and m["license"] == "Apache-2.0" and m["metadata"]["version"] == __version__ and "不用于" in m["description"] and len(t.splitlines()) < 500
def test_links_resolve():
    for f in [K/"SKILL.md", *(K/"references").glob("*.md")]:
        for x in re.findall(r"\]\(((?!http)[^)]+)\)", f.read_text("utf-8")): assert (f.parent/x).is_file(), (f, x)
def test_template_is_valid(): cli.normalise(J(K/"assets/brief.template.json"))
def test_commands_exist():
    import argparse
    names = set(next(a for a in cli.parser()._actions if isinstance(a, argparse._SubParsersAction)).choices); t = "".join(f.read_text("utf-8") for f in K.rglob("*.md")); assert set(re.findall(r"`fsc ([a-z]+)", t)) <= names
def test_tools_exist():
    pytest.importorskip("mcp"); import asyncio; from mcp import Client; from footage_scout import mcp_server as ms
    async def m():
        async with Client(ms.mcp) as c: return {t.name: t.input_schema["properties"] for t in (await c.list_tools()).tools}
    ts = asyncio.run(m()); t = fm()[1]; assert set(ts) <= set(re.findall(r"`?([a-z]+_[a-z]+|doctor)", t)) | {"register_download", "check_license"}
    for n, a in re.findall(r"\b([a-z]+_[a-z]+)\(([a-z_]+)=", "".join(f.read_text("utf-8") for f in K.rglob("*.md"))): assert a in ts[n], (n, a)
def test_topics_table():
    t = (K/"references/query-playbook.md").read_text("utf-8"); listed = set(re.findall(r"^\| `([a-z_]+)` \|", t, re.M)); real = {x for s in core.load_sources().values() if s["tier"] for x in s["topics"]}; assert listed == real
def test_source_list_matches_adapters():
    t = (K/"references/guided-sources.md").read_text("utf-8"); names = dict(nasa_images="NASA", ia="Internet Archive", loc="LOC", openbeelden="Open Beelden", esahubble="ESA/Hubble", esawebb="ESA/Webb", eso="ESO", noirlab="NOIRLab", isorepublic="ISO Republic", commons="Wikimedia Commons", dareful="Dareful", nasa_svs="NASA SVS", ia_nasa="Internet Archive", nps="NPS", usgs="USGS", nasa_eol="NASA EOL", netflix_open="Netflix Open Content")
    assert set(names) == set(providers.ADAPTERS) and all(v in t for v in names.values())
def test_rules_table(): assert set(re.findall(r"\| (R\d) ", (K/"references/license-matrix.md").read_text("utf-8"))) == {f"R{i}" for i in range(1, 10)}
def test_manifests():
    a, b = J(P/"plugin.json"), J(P/".claude-plugin/plugin.json"); assert a["name"] == b["name"] == "footage-scout" and a["version"] == b["version"] == __version__ and a["license"] == "Apache-2.0"
    for f in (P/"mcp.json", P/".mcp.json"): s = J(f)["mcpServers"]["footage-scout"]; assert s["command"] == "fsc" and s["args"] == ["mcp"]       # never an unpublished package name
    assert J(P/"mcp.json")["mcpServers"]["footage-scout"]["type"] == "stdio"
    for f in (R/".claude-plugin/marketplace.json", R/".agents/plugins/marketplace.json"):
        e = J(f)["plugins"][0]; s = e["source"]; s = s if isinstance(s, str) else s["path"]; assert (R/s).resolve() == P.resolve()
    y = yaml.safe_load((K/"agents/openai.yaml").read_text("utf-8")); assert y["policy"]["allow_implicit_invocation"] is True and y["dependencies"]["tools"][0]["value"] == "footage-scout"
def test_no_auto_install_or_force():
    t = "".join(f.read_text("utf-8") for f in [*K.rglob("*"), *P.glob("*.json"), P/".mcp.json"] if f.suffix in (".md", ".json", ".yaml")); assert "--force" not in t and "curl" not in t and "pip install" not in t and "bypass" not in t.lower()
def test_evals_shape():
    b = [json.loads(x) for x in (R/"evals/briefs.jsonl").read_text("utf-8").splitlines()]; assert len(b) == 20 and len({x["id"] for x in b}) == 20
    for x in b: assert all(cli.route(s, core.load_sources()) for s in cli.normalise(x["brief"])["shots"])
    t = [json.loads(x) for x in (R/"evals/triggers.jsonl").read_text("utf-8").splitlines()]; assert sum(x["should_trigger"] for x in t) == 10 and len(t) == 20
def test_oracle_agrees_with_gate():
    """Full cross-check of the eval oracle against gate.py: the gate may be stricter, never looser."""
    sys.path.insert(0, str(R/"evals")); import itertools, datetime as dt, run as ev; from footage_scout import gate, licenses; today = dt.datetime.now(dt.timezone.utc).date(); n = 0
    base = dict(licenses.make("CC-BY-4.0", "yes", "yes", "yes"))
    src = dict(core.load_sources()["nasa_images"], verified_at=today.isoformat())
    for at, d, co, ai, pr, use, aim, tr, gd in itertools.product(("yes", "no", "unknown"), ("yes", "no", "per_item"), ("yes", "no", "unknown"), ("allowed", "no_training", "no_generative_processing", "unknown"), (None, "x"), ("commercial", "personal_noncommercial"), ("none", "generative"), (False, True), ("per_rules", "hold", "block")):
        l = dict(base, attribution_required=at, derivatives=d, commercial=co, ai_use=ai, purpose_restriction=pr); b = dict(use=use, ai=aim, dataset_or_training=tr, documentary=False, strict_provenance=False); s = dict(src, gate_default=gd)
        ok = gate.evaluate(s, l, b, True, "unknown", today)["verdict"] in ("PASS", "WARN"); n += 1
        assert not ok or ev.oracle(s, l, b, {}, "unknown"), (l, b, gd)
    assert n == 5184
def test_examples_and_doc_links():
    m = core.read_json(R/"examples/寻镜-示例/footage_manifest.json", "manifest"); core.validate("edit_plan", J(R/"examples/寻镜-示例/edit_plan.json")); core.validate("edit_report", J(R/"examples/寻镜-示例/edit_report.json")); cli.normalise(J(R/"examples/示例选题.json")); assert m["assets"]
    for f in [R/"README.md", R/"README.en.md", *(R/"docs").glob("*.md")]:
        for x in re.findall(r'(?:\]\(|src=")((?!http|mailto|#)[^)"]+)', f.read_text("utf-8")): assert (f.parent/x).exists(), (f, x)
def test_adapter_count_in_docs():
    n = len(providers.ADAPTERS); s = [x for x in core.load_sources().values() if x["tier"]]; t = (R/"README.md").read_text("utf-8"); assert f"{len(s)} 个来源" in t and f"{n} 个源" in t and all(f"等 {sum(x['tier'] == k for x in s)} 个" in t for k in ("T3", "T4"))
