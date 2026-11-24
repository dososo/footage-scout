"""Optional local image-text scoring. Weights are pinned by revision, size and SHA-256, loaded from safetensors only, and nothing
is downloaded unless the user runs `fsc model --download`."""
import hashlib, importlib.util, os, pathlib, re, tempfile
from urllib.parse import urljoin, urlsplit
import httpx
from . import media
from .core import FscError, file_sha256

MODELS = {
    "clip": dict(scorer="clip", repo="laion/CLIP-ViT-B-32-laion2B-s34B-b79K", revision="1a25a446712ba5ee05982a381eed697ef9b435cf", license="MIT",
                 arch="ViT-B-32", needs=[], file="open_clip_model.safetensors", bytes=605143316,
                 sha256="ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6", extra={}),
    "siglip2": dict(scorer="siglip", repo="timm/ViT-B-16-SigLIP2", revision="eee10eff6dd8cabae2d7f379d4e8cfcd352030aa", license="Apache-2.0",
                    arch="ViT-B-16-SigLIP2", needs=["transformers"], file="open_clip_model.safetensors", bytes=1500786832,
                    sha256="d0a51069d2fa6c95b371b3bffd2a2c765c1815004798ee99f075290dbca73041",
                    extra={"open_clip_config.json": 944, "tokenizer.json": 34362885, "tokenizer_config.json": 46382, "special_tokens_map.json": 327}),
}
HOSTS = re.compile(r"(^|\.)(huggingface\.co|hf\.co)$")
_LOADED = {}


def base():
    return pathlib.Path(os.environ.get("FSC_CACHE_DIR") or pathlib.Path.home() / ".cache" / "footage-scout") / "models"


def folder(name):
    return base() / f"{name}-{MODELS[name]['revision'][:12]}"


def status(name="clip"):
    m, p = MODELS[name], folder(name) / MODELS[name]["file"]
    mods = [x for x in ("open_clip", "torch", "PIL", *m["needs"]) if importlib.util.find_spec(x) is None]
    ok = p.is_file() and not p.is_symlink() and p.stat().st_size == m["bytes"] and all((folder(name) / f).is_file() for f in m["extra"])
    return dict(model=name, repo=m["repo"], revision=m["revision"], license=m["license"], download_bytes=m["bytes"] + sum(m["extra"].values()),
                path=str(p), weights_present=ok, missing_modules=mods, ready=ok and not mods)


def _get(client, url, dest, size, sha=None):
    """HTTPS only, every redirect hop must stay on the Hugging Face hosts."""
    for _ in range(5):
        u = urlsplit(url)
        if u.scheme != "https" or u.username or u.port not in (None, 443) or not HOSTS.search(u.hostname or ""):
            raise FscError(f"model download refused off-list host: {u.hostname}")
        with client.stream("GET", url, follow_redirects=False) as r:
            if r.is_redirect:
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code != 200:
                raise FscError(f"model download: HTTP {r.status_code}")
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
            try:
                h, n = hashlib.sha256(), 0
                with os.fdopen(fd, "wb") as f:
                    for b in r.iter_bytes(1 << 20):
                        n += len(b)
                        if n > size:
                            raise FscError("model file is larger than pinned")
                        h.update(b)
                        f.write(b)
                    f.flush()
                    os.fsync(f.fileno())
                if n != size or sha and h.hexdigest() != sha:
                    raise FscError("model file does not match its pinned size or SHA-256")
                os.replace(tmp, dest)
                return
            finally:
                pathlib.Path(tmp).unlink(missing_ok=True)
    raise FscError("too many redirects")


def download(name="clip", client=None):
    m, d = MODELS[name], folder(name)
    d.mkdir(parents=True, exist_ok=True)
    c = client or httpx.Client(timeout=60, headers={"User-Agent": "footage-scout"}, trust_env=True)
    for f, size, sha in [(m["file"], m["bytes"], m["sha256"]), *((f, s, None) for f, s in m["extra"].items())]:
        p = d / f
        if p.is_symlink():
            raise FscError(f"symlink refused: {p}")
        if not (p.is_file() and p.stat().st_size == size and (not sha or file_sha256(p) == sha)):
            _get(c, f"https://huggingface.co/{m['repo']}/resolve/{m['revision']}/{f}", p, size, sha)
    return status(name)


class Model:
    def __init__(self, name):
        s = status(name)
        if s["missing_modules"]:
            raise FscError("vision is not installed (" + ", ".join(s["missing_modules"]) + "); run `fsc doctor`")
        if not s["weights_present"]:
            raise FscError(f"weights for {name} are not downloaded ({s['download_bytes']} bytes); the user can run `fsc model --download`")
        m = MODELS[name]
        if file_sha256(s["path"]) != m["sha256"]:
            raise FscError("weights do not match the pinned SHA-256; delete them and download again")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        import open_clip, torch
        self.torch, self.scorer = torch, m["scorer"]
        if name == "clip":
            self.net, _, self.pre = open_clip.create_model_and_transforms(m["arch"], pretrained=s["path"])
            self.tok = open_clip.get_tokenizer(m["arch"])
        else:
            loc = f"local-dir:{folder(name)}"
            self.net, _, self.pre = open_clip.create_model_and_transforms(loc)
            self.tok = open_clip.get_tokenizer(loc)
        self.net.eval()

    def similarity(self, images, texts):
        """Best cosine over the phrasings, one value per image."""
        t = self.torch
        with t.inference_mode():
            a = t.cat([self.net.encode_image(t.stack([self.pre(i) for i in images[k:k + 32]])) for k in range(0, len(images), 32)])
            b = self.net.encode_text(self.tok(texts))
            a, b = a / a.norm(dim=-1, keepdim=True), b / b.norm(dim=-1, keepdim=True)
            return (a @ b.T).max(dim=1).values.tolist()


def load(name="clip"):
    if name not in MODELS:
        raise FscError("vision model must be one of: " + ", ".join(MODELS))
    if name not in _LOADED:
        _LOADED[name] = Model(name)
    return _LOADED[name]


def allowed(brief):
    if brief["ai"] == "none":
        raise FscError("the brief says ai=none, so frames are not analysed by a local model; set ai to local_analysis to use vision")


def cells(sheet, n):
    """Cut a contact sheet back into its n tiles."""
    from PIL import Image
    w, h = media.CELL
    with Image.open(sheet, formats=["JPEG"]) as im:
        im = im.convert("RGB")
        cols = min(3, n)
        if im.size != (cols * w, -(-n // cols) * h):
            raise FscError("contact sheet has an unexpected size")
        return [im.crop((i % cols * w, i // cols * h, i % cols * w + w, i // cols * h + h)) for i in range(n)]


def dhash(im):
    g = im.convert("L").resize((9, 8))
    p = list(g.tobytes())
    if max(p) - min(p) < 24:        # flat tiles look alike and would pair unrelated films
        return None
    return sum((p[r * 9 + c] > p[r * 9 + c + 1]) << (r * 8 + c) for r in range(8) for c in range(8))


def normalise(v):
    lo, hi = min(v), max(v)
    return [(x - lo) / (hi - lo) if hi > lo else 0.5 for x in v]
