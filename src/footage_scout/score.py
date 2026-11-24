"""Write relevance back into candidates.json: an agent's 1-5 rating of the contact sheets, or a local vision model."""
import pathlib
from . import media, rank, vision
from .core import FscError, ProjectLock, read_json, validate, write_json

MAX_VISION = 20
WEAK = {"clip": 0.22}       # raw cosine under this is reported as a weak match; a heuristic


def usable(c): return c["gate"]["verdict"] in ("PASS", "WARN") and bool(c["file_url"])


def apply(path, rel, sources, sims=None, notes=()):
    """rel: {(shot_id, asset_id): (relevance, scorer)}. Only relevance, score and order change; licence fields never do."""
    with ProjectLock(pathlib.Path(path).resolve().parent):
        cs = read_json(path, "candidate_set")
        known = {(c["shot_id"], c["asset_id"]) for c in cs["candidates"]}
        if set(rel) - known:
            raise FscError("rating names a shot or asset that is not in the list")
        out = []
        for shot in cs["brief"]["shots"]:
            group = []
            for c in (c for c in cs["candidates"] if c["shot_id"] == shot["shot_id"]):
                k = (c["shot_id"], c["asset_id"])
                if k in rel:
                    c = dict(c, relevance=round(rel[k][0], 4), scorer=rel[k][1])
                    c.pop("similarity", None)
                    if sims and k in sims:
                        c["similarity"] = round(sims[k], 4)
                group.append(c)
            r = rank.rank(group, shot, cs["brief"], sources)
            out += sorted(r, key=lambda c: not usable(c))
        cs = validate("candidate_set", dict(cs, candidates=out, notices=cs["notices"] + [n for n in notes if n not in cs["notices"]]))
        write_json(path, cs)
    return cs


def rate(path, ratings, sources):
    rel = {}
    for shot, asset, stars in ratings:
        if str(stars) not in ("1", "2", "3", "4", "5"):
            raise FscError("a rating is a whole number from 1 to 5")
        if (shot, asset) in rel:
            raise FscError(f"rated twice: {shot} {asset}")
        rel[shot, asset] = ((int(stars) - 1) / 4, "agent")
    if not rel:
        raise FscError("no ratings given")
    return apply(path, rel, sources)


def by_vision(path, name, http, sources, model=None):
    cs = read_json(path, "candidate_set")
    vision.allowed(cs["brief"])
    model = model or vision.load(name)
    root = pathlib.Path(path).resolve().parent
    ids = list(dict.fromkeys(c["asset_id"] for c in sorted(cs["candidates"], key=lambda c: not usable(c)) if c["gate"]["verdict"] != "BLOCK"))
    notes, tiles = [], {}
    if len(ids) > MAX_VISION:
        notes.append(f"vision: only {MAX_VISION} of {len(ids)} assets were scored")
    for i in ids[:MAX_VISION]:
        try:
            d = media.inspect(root, i, http, sources)
            if d["sheet"]:
                tiles[i] = vision.cells(d["sheet"], d["tiles"])
            else:
                notes.append(f"vision: {i}: no image to score")
        except FscError as e:
            notes.append(f"vision: {i}: {e}")
    if not tiles:
        raise FscError("no candidate has an image to score: " + " | ".join(notes)[:600])
    hashes = {i: [h for h in map(vision.dhash, t) if h is not None] for i, t in tiles.items()}
    order = list(tiles)
    for n, a in enumerate(order):
        for b in order[n + 1:]:
            # a shared title slate is not a duplicate: most pictures of the shorter sheet must match
            s, l = sorted((hashes[a], hashes[b]), key=len)
            if s and sum(any((x ^ y).bit_count() <= 4 for y in l) for x in s) * 2 > len(s):
                notes.append(f"possible duplicate: {a} and {b}")
    rel, sims = {}, {}
    for shot in cs["brief"]["shots"]:
        mine = [c["asset_id"] for c in cs["candidates"] if c["shot_id"] == shot["shot_id"] and c["asset_id"] in tiles]
        if not mine:
            continue
        # the description only: a one-word query such as "waves" also matches abstract graphics
        best = [max(model.similarity(tiles[i], [shot["description"]])) for i in mine]
        for i, b, r in zip(mine, best, vision.normalise(best)):
            rel[shot["shot_id"], i], sims[shot["shot_id"], i] = (r, model.scorer), b
        if model.scorer in WEAK and max(best) < WEAK[model.scorer]:
            notes.append(f"{shot['shot_id']}: weak match, best similarity {max(best):.3f}; look at the sheets")
    return apply(path, rel, sources, sims, notes)
