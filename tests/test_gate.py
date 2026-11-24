import itertools as it, datetime as dt, inspect, pytest
from footage_scout import gate, licenses
from conftest import TODAY
TRI = ("yes", "no", "unknown", "per_item")
AI = ("allowed", "no_training", "no_generative_processing", "disclose_ai_modification", "unknown", "per_item")

def expected(use, ai, der, com, aiu, train, edit, doc, gd):
    """Independent table: (rule, severity, predicate) written from the spec, not from gate.py."""
    unk = {"unknown", "per_item"}
    table = [("", 3, gd == "block"), ("", 2, gd == "hold"), ("R1", 3, (der, edit) == ("no", True)),
             ("R2", 3, (com, use) == ("no", "commercial")), ("R3", 3, (aiu, ai) == ("no_generative_processing", "generative")),
             ("R4", 3, (aiu, train) == ("no_training", True)),
             ("R5", 2, bool({der, com} & unk) or (aiu in unk and (train or ai == "generative"))), ("R8", 1, doc)]
    on = [(r, s) for r, s, p in table if p]
    return ["PASS", "WARN", "HOLD", "BLOCK"][max([s for _, s in on], default=0)], sorted(r for r, _ in on if r)

def src(gd="per_rules", **k): return dict(dict(gate_default=gd, verified_at="2026-11-20", verify_status="official_read"), **k)

def test_full_matrix(brief):
    n = leaks = 0
    for use, ai, der, com, aiu, train, edit, doc, gd in it.product(("personal_noncommercial", "commercial"),
            ("none", "local_analysis", "generative"), TRI, TRI, AI, (0, 1), (0, 1), (0, 1), ("per_rules", "hold", "block")):
        b = dict(brief, use=use, ai=ai, dataset_or_training=bool(train), documentary=bool(doc))
        g = gate.evaluate(src(gd), licenses.make("X-1", "yes", der, com, aiu), b, bool(edit), "ai_generated", TODAY)
        v, r = expected(use, ai, der, com, aiu, bool(train), bool(edit), bool(doc), gd)
        assert (g["verdict"], g["rules"]) == (v, r), (use, ai, der, com, aiu, train, edit, doc, gd)
        n += 1
        leaks += v in ("HOLD", "BLOCK") and g["verdict"] in ("PASS", "WARN")
    assert n == 2*3*4*4*6*8*3 and leaks == 0

ok = lambda **k: dict(licenses.make("CC-BY-4.0", "yes", "yes", "yes"), **k)
@pytest.mark.parametrize("lic,kw,s,v,r", [
    (ok(license_id="UNKNOWN"), {}, {}, "HOLD", ["R5"]), (ok(attribution_required="per_item"), {}, {}, "HOLD", ["R5"]),
    (ok(license_id="CC-BY-SA-4.0"), {}, {}, "WARN", ["R6"]), (ok(license_id="CC-BY-NC-SA-4.0"), {}, {}, "WARN", ["R6"]),
    (ok(license_id="NASA-media"), {}, {}, "PASS", []), (ok(third_party_rights_flag=True), {}, {}, "WARN", ["R7"]),
    (ok(), dict(documentary=True, strict_provenance=True), {}, "BLOCK", ["R8"]),
    (ok(purpose_restriction="eu"), {}, {}, "HOLD", ["R9"]), (ok(purpose_restriction="eu"), dict(purpose="EU "), {}, "PASS", []),
    (ok(), {}, dict(verified_at="2026-05-28"), "PASS", []), (ok(), {}, dict(verified_at="2026-05-27"), "HOLD", ["R5"]),
    (ok(), {}, dict(verified_at="2027-01-01"), "HOLD", ["R5"])])
def test_rules(brief, lic, kw, s, v, r):
    assert gate.evaluate(src(**s), lic, dict(brief, **kw), True, "ai_generated", TODAY) == dict(verdict=v, rules=r)

def test_no_force():
    for f in (gate.evaluate, gate.gate_candidate): assert not {"force", "override"} & set(inspect.signature(f).parameters)

@pytest.mark.parametrize("url,lid,com,der", [
    ("https://creativecommons.org/licenses/by/3.0", "CC-BY-3.0", "yes", "yes"),
    ("http://creativecommons.org/licenses/by-sa/3.0/nl/", "CC-BY-SA-3.0-NL", "yes", "yes"),
    ("https://creativecommons.org/licenses/by-nc-nd/4.0/deed.en", "CC-BY-NC-ND-4.0", "no", "no"),
    ("https://creativecommons.org/publicdomain/mark/1.0/", "PDM-1.0", "yes", "yes"),
    ("https://creativecommons.org.evil.com/licenses/by/4.0/", "UNKNOWN", "unknown", "unknown"),
    ("https://evil.com/?u=creativecommons.org/licenses/by/4.0/", "UNKNOWN", "unknown", "unknown"),
    ("public domain", "UNKNOWN", "unknown", "unknown"), (None, "UNKNOWN", "unknown", "unknown"), (["x"], "UNKNOWN", "unknown", "unknown")])
def test_license_urls(url, lid, com, der):
    x = licenses.from_url(url); assert (x["license_id"], x["commercial"], x["derivatives"]) == (lid, com, der)

def test_today_is_utc(brief, monkeypatch):
    class D(dt.datetime):
        @classmethod
        def now(cls, tz=None): assert tz is dt.timezone.utc; return cls(2026, 11, 24, 3, tzinfo=tz)
    monkeypatch.setattr(gate.dt, "datetime", D)
    assert gate.evaluate(src(verified_at="2026-11-24"), ok(), brief)["verdict"] == "PASS"

def test_stale(brief): assert gate.evaluate(src(verify_status="stale"), ok(), brief, today=TODAY) == dict(verdict="HOLD", rules=["R5"])
