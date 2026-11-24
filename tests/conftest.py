import copy, datetime as dt, pathlib, pytest
from footage_scout import licenses
FX = pathlib.Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 11, 24)
@pytest.fixture
def fx(): return lambda n: (FX / n).read_bytes()
@pytest.fixture
def brief():
    return dict(schema_version="1.0.0", title="t", use="personal_noncommercial", ai="none", orientation="landscape",
                shots=[dict(shot_id="s1", description="forest", queries=["forest"], topics=["nature"], duration_s=5)])
@pytest.fixture
def manifest():
    h = "0" * 64
    return copy.deepcopy(dict(schema_version="1.0.0", project="p", brief_sha256=h, assets=[dict(
        asset_id="commons:1", source_id="commons", path="media/a.webm", sha256=h, source_page="https://x.org/a",
        download_host="x.org", tasl=dict(title="T", author=None, source="https://x.org/a", license="CC0-1.0"),
        provenance="unknown", license=dict(licenses.make("CC0-1.0", "no", "yes", "yes"), terms_snapshot_sha256=h),
        gate=dict(verdict="PASS", rules=[], artifact_sha256=h), media=None, segment=None,
        downloaded_at="2026-11-24T00:00:00Z", modifications=[])]))
@pytest.fixture(autouse=True)
def contact(monkeypatch): monkeypatch.setenv("FSC_CONTACT_URL", "https://example.org/fsc")
