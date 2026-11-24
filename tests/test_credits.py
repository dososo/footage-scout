from footage_scout.credits import build
def test_bilingual_missing_and_escape(manifest):
    manifest["assets"][0]["tasl"]["title"] = "a\n# [x](http://e) <script>"
    t = build(manifest); assert "missing" in t and "素材署名" in t and "Footage credits" in t
    assert "\n# [x]" not in t and "<script>" not in t
