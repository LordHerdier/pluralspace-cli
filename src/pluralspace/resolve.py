"""Turn user-supplied names and ids into API objects."""

from .api_client import PluralspaceAPI
from .errors import UsageError


def _id_matches(member_id: str, ref: str) -> bool:
    ref = ref.lower()
    return member_id.lower() == ref or (
        len(ref) >= 6 and member_id.lower().endswith(ref)
    )


def resolve_front_type(types, ref: str) -> dict:
    """Match a front type by name or slug, case-insensitively."""
    hits = [
        t
        for t in types
        if ref.lower() in (t["name"].lower(), (t.get("slug") or "").lower())
    ]
    if len(hits) != 1:
        names = ", ".join(t["name"] for t in types)
        raise UsageError(
            f"front type '{ref}' not found; available: {names}"
            if not hits
            else f"front type '{ref}' is ambiguous"
        )
    return hits[0]


def match_member_exact(candidates, ref: str) -> list:
    """Members whose `name`, `display_name`, or `display_label` equals ref
    (case-insensitive, whole string), or whose id matches ref. No prefix or
    substring matching; this is what writes use."""
    low = ref.strip().lower()
    if not low:
        return []
    return [
        m
        for m in candidates
        if _id_matches(m["id"], low)
        or low
        in {
            (m.get(k) or "").strip().lower()
            for k in ("name", "display_name", "display_label")
        }
        - {""}
    ]


def _describe_member(m: dict) -> str:
    label = m.get("display_label") or m.get("display_name") or m.get("name") or "?"
    plain = m.get("name")
    named = f" aka {plain!r}" if plain and plain != label else ""
    return f"{label}{named} ({m['id'][-8:]})"


def resolve_member(api: PluralspaceAPI, ref: str, exact: bool = False) -> dict:
    """Resolve a name or id (or id suffix, as shown by `members`) to one member.

    exact=False (reads) falls back to a lone fuzzy search hit. exact=True
    (writes) only accepts a whole-string match on name/display name or an id;
    near misses are listed in the error but never used.
    """
    search = api.search_members(ref)
    if exact:
        # /members has the plain `name` but omits custom fronts; the search
        # has custom fronts but only the display label. Use both, keyed by id.
        merged = {m["id"]: m for m in search}
        merged.update({m["id"]: m for m in api.members()})
        hits = match_member_exact(merged.values(), ref)
        if not hits:
            near = ", ".join(_describe_member(m) for m in search)
            raise UsageError(
                f"no member exactly matches '{ref}' (writes need an exact name or id)"
                + (f"; did you mean: {near}" if near else "")
            )
    else:
        exact_hits = match_member_exact(search, ref)
        hits = exact_hits or (search if len(search) == 1 else [])
        if not hits:
            # `members` lists ids by suffix; fall back to that listing for id lookups
            hits = [m for m in api.members() if _id_matches(m["id"], ref)]
        if not hits:
            raise UsageError(f"no member matches '{ref}'")
    if len(hits) > 1:
        ids = ", ".join(_describe_member(m) for m in hits)
        raise UsageError(f"'{ref}' is ambiguous: {ids}; use the id suffix")
    return hits[0]


def resolve_mood(moods, ref: str) -> dict:
    """Match a mood by exact name (case-insensitive). Prefixes are not accepted."""
    low = ref.strip().lower()
    hits = [m for m in moods if m["name"].lower() == low]
    if len(hits) != 1:
        names = ", ".join(m["name"] for m in moods)
        raise UsageError(
            f"mood '{ref}' "
            + ("not found" if not hits else "is ambiguous")
            + f" (moods must match exactly); available: {names}"
        )
    return hits[0]
