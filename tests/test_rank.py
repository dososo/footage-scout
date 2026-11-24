from footage_scout.rank import rank
from footage_scout.core import load_sources
S = load_sources()
def c(i, t, sid="commons", **m): return dict(asset_id=i, source_id=sid, title=t, **({"media": m} if m else {}))
def test_order_diversity_bounds(brief):
    sh = brief["shots"][0]; cs = [c("a", "city"), c("b", "forest", duration_s=9, width=1920, height=1080), c("c", "forest", "nasa_images")]
    r = rank(cs, sh, brief, S); assert r[0]["asset_id"] == "b" and all(0 <= x["score"] <= 1 and x["scorer"] == "none" for x in r)
    assert [x["asset_id"] for x in rank(cs[::-1], sh, brief, S)] == [x["asset_id"] for x in r] and rank([], sh, brief, S) == []
