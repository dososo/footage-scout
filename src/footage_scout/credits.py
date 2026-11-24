import re
from .core import validate

L = {"zh": ("素材署名", "作者", "来源", "许可", "修改", "未修改", "【待清权】"),
     "en": ("Footage credits", "Author", "Source", "License", "Changes", "unmodified", "[NOT CLEARED]")}


def _c(s):
    s = re.sub(r"\s+", " ", s or "missing").strip()
    return re.sub(r"([\\`*_\[\]<>#|!])", r"\\\1", s)


def build(manifest, langs=("zh", "en")):
    validate("manifest", manifest)
    out = []
    for lang in langs:
        h, a, s, l, ch, un, nc = L[lang]
        out += [f"# {h}", ""]
        for x in manifest["assets"]:
            t = x["tasl"]
            url = re.sub(r"[\s<>]", "", t["source"])
            mods = list(x["modifications"])
            if x["segment"]:
                mods.append(f"{x['segment']['in_s']}–{x['segment']['out_s']} s")
            hold = "" if x["gate"]["verdict"] in ("PASS", "WARN") else nc + " "
            out.append(f"- {hold}{_c(t['title'])} | {a}: {_c(t['author'])} | {s}: <{url}> | {l}: {_c(t['license'])} | "
                       f"{ch}: {_c('; '.join(mods)) if mods else un}")
        out.append("")
    return "\n".join(out)
