"""mood."""

from ...api_client import APIError, PluralspaceAPI
from ...credentials import PassStore
from ...errors import UsageError
from ...fronts import DRY_RUN_HEADER
from ...resolve import resolve_mood
from ..common import (
    _authed,
    _emit_json,
    add_dry_run,
    add_json,
    snapshot_after,
    snapshot_before,
)


def _mood_list(args, api, store) -> int:
    moods = _authed(api, store, api.moods)
    if args.json:
        return _emit_json(moods)
    for m in moods:
        print(f"{m['name']:<12} {m.get('tagline', '')}")
    return 0


def _mood_preview(args, api, store) -> int:
    if not (args.clear or args.name):
        raise UsageError("--dry-run needs a mood NAME or --clear")

    def preview():
        before = api.atmosphere().get("mood_label") or "(none)"
        after = "(none)" if args.clear else resolve_mood(api.moods(), args.name)["name"]
        return before, after

    before, after = _authed(api, store, preview)
    print(DRY_RUN_HEADER)
    if before.casefold() == after.casefold():
        print(f"  mood: {before} (unchanged)")
    else:
        print(f"  mood: {before} -> {after}")
    return 0


def mood_state(atmosphere: dict) -> dict:
    """The {"id", "label"} form of the dashboard's current mood."""
    return {"id": atmosphere.get("mood"), "label": atmosphere.get("mood_label")}


def _mood_apply(args, api, store) -> int:
    recorded = False
    wrote = False
    target_id = None

    def write():
        nonlocal recorded, wrote, target_id
        target_id = None
        if args.name and not args.clear:
            target_id = resolve_mood(api.moods(), args.name)["id"]
        before = mood_state(api.atmosphere())
        if before["id"] != target_id:
            snapshot_before(args, "mood", "mood", before)
            recorded = True
        wrote = True
        if args.clear:
            api.clear_mood()
        else:
            api.set_mood(target_id)

    if args.clear or args.name:
        _authed(api, store, write)
    atmosphere = _authed(api, store, api.atmosphere)
    if recorded:
        snapshot_after(args, mood_state(atmosphere))
    if wrote and atmosphere.get("mood") != target_id:
        raise APIError(
            "the write was accepted but the mood isn't as expected (now "
            f"{atmosphere.get('mood_label') or '(none)'}). Check the app"
        )
    if args.json:
        return _emit_json(atmosphere)
    print(f"Mood: {atmosphere.get('mood_label') or '(none)'}")
    print(atmosphere.get("tagline", ""))
    return 0


def cmd_mood(args, api: PluralspaceAPI, store: PassStore) -> int:
    if args.list:
        return _mood_list(args, api, store)
    if args.dry_run:
        return _mood_preview(args, api, store)
    return _mood_apply(args, api, store)


def register(sub) -> None:
    p = sub.add_parser("mood", help="show, set or clear the system mood")
    p.add_argument("name", nargs="?", help="mood to set (exact name)")
    p.add_argument("--list", action="store_true", help="list available moods")
    p.add_argument("--clear", action="store_true", help="clear the current mood")
    add_dry_run(p)
    add_json(p)
    p.set_defaults(func=cmd_mood)
