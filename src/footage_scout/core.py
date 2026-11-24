"""Shared: errors, canonical JSON, schema loading, sources, safe atomic writes."""
import hashlib, json, os, pathlib, tempfile, threading, time
from contextlib import contextmanager
from functools import lru_cache
import yaml
from jsonschema import Draft202012Validator

HERE = pathlib.Path(__file__).resolve().parent


class FscError(Exception):
    pass


def _res(kind, name):
    for base in (HERE / kind, HERE.parents[1] / kind):
        if (base / name).is_file():
            return base / name
    raise FscError(f"missing packaged resource {kind}/{name}")


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


@lru_cache
def _validator(name):
    s = json.loads(_res("schemas", f"{name}.schema.json").read_text("utf-8"))
    return Draft202012Validator(s)


def validate(name, obj):
    errs = sorted(_validator(name).iter_errors(obj), key=lambda e: list(map(str, e.path)))
    if errs:
        e = errs[0]
        raise FscError(f"{name} schema: /{'/'.join(map(str, e.path))}: {e.message[:300]}")
    return obj


@lru_cache
def load_sources():
    d = yaml.safe_load(_res("data", "sources.yaml").read_text("utf-8"))
    validate("sources", d)
    out = {s["id"]: s for s in d["sources"]}
    if len(out) != len(d["sources"]):
        raise FscError("duplicate source id")
    from .health import overlay
    return overlay(out, read_json(_res("data", "health.json"), "health"))


def read_json(path, schema=None):
    try:
        obj = json.loads(pathlib.Path(path).read_text("utf-8"))
    except (OSError, ValueError) as e:
        raise FscError(f"cannot read {path}: {e}") from e
    return validate(schema, obj) if schema else obj


def safe_path(root, *parts):
    """Path under root; rejects traversal and any symlink below root."""
    root = pathlib.Path(root).resolve()
    p = root
    for part in parts:
        if part in ("", ".", "..") or "/" in part or "\\" in part or "\0" in part:
            raise FscError(f"unsafe path component {part!r}")
        p = p / part
        if p.is_symlink():
            raise FscError(f"symlink refused: {p}")
    if not p.resolve().is_relative_to(root):
        raise FscError(f"path escapes root: {p}")
    return p


def atomic_write(path, data: bytes):
    path = pathlib.Path(path)
    if path.is_symlink():
        raise FscError(f"symlink refused: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path, obj):
    atomic_write(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode())


class ProjectLock:
    """O_EXCL lock whose heartbeat is refreshed; abandoned locks expire."""

    def __init__(self, root, ttl=900):
        self.path, self.ttl, self.token = safe_path(root, ".fsc.lock"), ttl, os.urandom(8).hex()

    def __enter__(self):
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(self.token)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.lstat().st_mtime < self.ttl:
                        break
                    self.path.unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
        raise FscError("project is locked by another fsc process")

    def _mine(self):
        try:
            return self.path.read_text() == self.token
        except OSError:
            return False

    def beat(self):
        if not self._mine():
            raise FscError("project lock lost")
        os.utime(self.path)

    @contextmanager
    def alive(self, every=60):
        """Keep beating while a long blocking call runs, so another process cannot expire the lock underneath it."""
        stop = threading.Event()

        def loop():
            while not stop.wait(every):
                try:
                    self.beat()
                except (FscError, OSError):
                    return
        t = threading.Thread(target=loop, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop.set()
            t.join()
        self.beat()

    def __exit__(self, *a):
        if self._mine():
            self.path.unlink(missing_ok=True)
