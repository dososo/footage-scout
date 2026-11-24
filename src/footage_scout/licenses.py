"""Map explicit licence URLs. Free text is never interpreted as permission."""
import re
from urllib.parse import urlsplit


def make(license_id="UNKNOWN", attr="unknown", der="unknown", com="unknown", ai="unknown", third=False, url=None):
    d = dict(license_id=license_id, attribution_required=attr, derivatives=der, commercial=com, ai_use=ai,
             third_party_rights_flag=third, purpose_restriction=None)
    if url and re.match(r"https?://", url):
        d["terms_url"] = url
    return d


def from_url(url, third=False):
    if not isinstance(url, str):
        return make(third=third)
    try:
        u = urlsplit(url.strip())
        host = u.hostname
    except ValueError:
        return make(third=third)
    if u.scheme not in ("http", "https") or host not in ("creativecommons.org", "www.creativecommons.org"):
        return make(third=third)
    p = u.path.rstrip("/").lower()
    p = re.sub(r"/(deed|legalcode)(\.[a-z_-]+)?$", "", p)
    if re.fullmatch(r"/publicdomain/zero/1\.0", p):
        return make("CC0-1.0", "no", "yes", "yes", third=third, url=url)
    if re.fullmatch(r"/publicdomain/mark/1\.0", p):
        return make("PDM-1.0", "no", "yes", "yes", third=third, url=url)
    if p == "/licenses/publicdomain":
        return make("CC-PublicDomain-legacy", "no", "yes", "yes", third=third, url=url)
    m = re.fullmatch(r"/licenses/(by(?:-nc)?(?:-(?:nd|sa))?)/(\d\.\d)(/[a-z-]+)?", p)
    if not m:
        return make(third=third, url=url)
    k = m[1].split("-")
    return make(f"CC-{m[1].upper()}-{m[2]}" + (m[3] or "").replace("/", "-").upper(), "yes",
                "no" if "nd" in k else "yes", "no" if "nc" in k else "yes", third=third, url=url)


def from_source(src, third=False):
    if src["license_model"] == "per_item" or src["gate_default"] != "per_rules":
        return make(third=third)
    return make(src["license_id"], src["attribution_required"], src["derivatives"], src["commercial"], src["ai_use"],
                third, src.get("terms_url"))
