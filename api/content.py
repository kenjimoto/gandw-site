"""VERSUS published content: the upload page's store (content framework, step 3).

The game ships with content built from the workbook in the VERSUS repo. An author (or an admin)
uploads a workbook on /admin/versus/; the page checks every row with the game's own rules
(the game's workbook-check.js) and sends the result here as plain content. Each upload is a
numbered version. An author can stage a version (only they see it in the game) and publish one
(everyone sees it). Publishing an older version is the rollback.

Stored in the accounts table:

    pk VC   sk seq            {n}                         the last version number
    pk VC   sk v#<000123>     {n, content (JSON text)}
    pk VC   sk m#<000123>     {n, base, core, note, by, at, size, counts, published_at?, published_by?}
    pk VC   sk live           {n, at, by}                 the published version
    pk VC   sk stage#<user>   {n, at}                     what that author sees while staging

The page has already run the full checks; this module checks the shape again, because the
game loads whatever is published for everyone. It never runs content: it is data the game reads.
"""
import json
import re

MAX_CONTENT = 250_000           # bytes of JSON per version (a DynamoDB item tops out at 400 KB)
KEYS = {                         # what a version may hold, and the type of each part
    "npcs": list, "quests": list, "bosses": list, "enemies": list,
    "items": dict, "lootTables": dict, "schedules": dict,
}
ID_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
BASE_RE = re.compile(r"^[0-9a-f]{16}$")
CORE_RE = re.compile(r"^\d+\.\d+\.\d+$")
MAX_LIST = 2_000                 # rows of any one kind


class ContentError(ValueError):
    pass


def check(content, base, core):
    """Raise ContentError unless this is plausible VERSUS content. Returns (json text, counts)."""
    if not isinstance(content, dict) or not content:
        raise ContentError("content must be an object with the workbook's parts.")
    extra = sorted(set(content) - set(KEYS))
    if extra:
        raise ContentError("content has parts the game doesn't know: " + ", ".join(extra))
    for need in ("npcs", "quests", "items", "bosses"):
        if need not in content:
            raise ContentError(f"content is missing {need}.")
    counts = {}
    for k, v in content.items():
        if not isinstance(v, KEYS[k]):
            raise ContentError(f"{k} must be a {'list' if KEYS[k] is list else 'table'}.")
        if len(v) > MAX_LIST:
            raise ContentError(f"{k} has more than {MAX_LIST} entries.")
        counts[k] = len(v)
        if KEYS[k] is list:
            ids = set()
            for i, row in enumerate(v):
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not ID_RE.match(row["id"]):
                    raise ContentError(f"{k} entry {i + 1} needs an id of letters, digits and _.")
                if row["id"] in ids:
                    raise ContentError(f"{k}: the id {row['id']} appears twice.")
                ids.add(row["id"])
        else:
            for key, row in v.items():
                if not ID_RE.match(key):
                    raise ContentError(f"{k}: {key!r} is not a valid id.")
                if k == "lootTables" and not isinstance(row, list):
                    raise ContentError(f"lootTables.{key} must be a list of rows.")
                if k == "items" and not isinstance(row, dict):
                    raise ContentError(f"items.{key} must be an object.")
    if not isinstance(base, str) or not BASE_RE.match(base):
        raise ContentError("base must be the 16-character fingerprint of the game's workbook.")
    if not isinstance(core, str) or not CORE_RE.match(core):
        raise ContentError("core must be a version like 2.3.0.")
    text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode()) > MAX_CONTENT:
        raise ContentError(f"content is too large ({len(text.encode()) // 1000} KB; {MAX_CONTENT // 1000} KB max).")
    return text, counts


def sk(n):
    """The item holding a version's content."""
    return f"v#{int(n):06d}"


def mk(n):
    """The item holding a version's details (listed without loading every version's content)."""
    return f"m#{int(n):06d}"


def meta(item):
    """A version as the admin page lists it (without the content)."""
    return {"version": f"v{int(item['n'])}", "n": int(item["n"]), "base": item.get("base"), "core": item.get("core"),
            "note": item.get("note", ""), "by": item.get("by"), "at": item.get("at"), "size": int(item.get("size", 0)),
            "counts": item.get("counts") or {}, "published_at": item.get("published_at"), "published_by": item.get("published_by")}


def as_script(payload):
    """window.VERSUS_LIVE = {...}; as a script the game loads before it starts. JSON is valid
    JavaScript; U+2028/2029 and '</' are escaped so the text is safe in any context."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    body = body.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("</", "<\\/")
    return "window.VERSUS_LIVE=" + body + ";\n"
