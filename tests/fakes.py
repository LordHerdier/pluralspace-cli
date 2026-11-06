"""A stateful stand-in for PluralspaceAPI that behaves like the real site did
in the HAR captures and live probes (see ROADMAP/undo notes):

- start-multi keeps rows whose member and type are unchanged, and a type
  change closes the row and opens a new one (new id, new start time);
- the dashboard (`current_fronts`) shows one live row per member, but the
  calendar lists every live row;
- reopening a row (PATCH ended_at -> null) is accepted even next to another
  live row, so only the planner stands between that and a duplicate.
"""

from datetime import datetime, timedelta, timezone

from pluralspace.api_client import CalendarState

FRONT, CO_FRONT = "t-front", "t-cofront"
TYPES = [
    {"id": FRONT, "name": "Front", "slug": "front"},
    {"id": CO_FRONT, "name": "Co-Front", "slug": "co-front"},
]
TYPE_NAMES = {t["id"]: t["name"] for t in TYPES}
MEMBERS = [
    {"id": "m-ada", "name": "Ada", "display_label": "Ada"},
    {"id": "m-bo", "name": "Bo", "display_label": "Bo"},
    {"id": "m-cy", "name": "Cy", "display_label": "Cy"},
]
LABELS = {m["id"]: m["display_label"] for m in MEMBERS}
MOODS = [
    {"id": "mood-calm", "name": "Calm", "tagline": "ok"},
    {"id": "mood-tired", "name": "Tired", "tagline": "zzz"},
]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class FakeServer:
    def __init__(self):
        self.rows = {}  # id -> normalized calendar row
        self.mood = {"id": None, "label": None}
        self.calls = []
        self.can_edit = True
        self._n = 0
        self._clock = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
            minutes=2
        )

    # -- test setup -------------------------------------------------------

    def tick(self):
        self._clock += timedelta(seconds=5)
        return _iso(self._clock)

    def start(self, member_id, type_id=FRONT, comment=None):
        self._n += 1
        row = {
            "id": f"row{self._n}",
            "member_id": member_id,
            "type_id": type_id,
            "started_at": self.tick(),
            "ended_at": None,
            "comment": comment,
            "label": LABELS[member_id],
            "type_name": TYPE_NAMES[type_id],
        }
        self.rows[row["id"]] = row
        return row

    def live(self):
        return [r for r in self.rows.values() if r["ended_at"] is None]

    def live_ids(self):
        return {r["member_id"]: r["id"] for r in self.live()}

    def _end(self, row):
        row["ended_at"] = self.tick()

    # -- the PluralspaceAPI surface the commands use ----------------------

    def current_fronts(self):
        latest = {}
        for r in self.live():  # dashboard hides a member's extra live rows
            if (
                r["member_id"] not in latest
                or r["started_at"] > latest[r["member_id"]]["started_at"]
            ):
                latest[r["member_id"]] = r
        return [
            {
                "id": r["id"],
                "member_id": r["member_id"],
                "system_front_type_id": r["type_id"],
                "started_at": r["started_at"],
                "comment": r["comment"],
                "member": {"display_label": r["label"]},
                "front_type": {"name": r["type_name"]},
            }
            for r in latest.values()
        ]

    def front_types(self):
        return TYPES

    def members(self, *a, **kw):
        return MEMBERS

    def search_members(self, query):
        return [m for m in MEMBERS if query.lower() in m["name"].lower()]

    def set_fronts(self, fronters, comment=None, silent=False):
        self.calls.append(("set_fronts", dict(fronters), comment, silent))
        for row in self.live():
            if fronters.get(row["member_id"]) != row["type_id"]:
                self._end(row)
        keep = {r["member_id"] for r in self.live()}
        for member_id, type_id in fronters.items():
            if member_id not in keep:
                self.start(member_id, type_id, comment)

    def end_all(self):
        self.calls.append(("end_all",))
        for row in self.live():
            self._end(row)

    def end_front(self, member_id):
        self.calls.append(("end_front", member_id))
        for row in self.live():
            if row["member_id"] == member_id:
                self._end(row)

    def delete_front(self, front_id):
        self.calls.append(("delete_front", front_id))
        self.rows.pop(front_id, None)

    def reopen_front(self, row, tz_name):
        self.calls.append(("reopen_front", row["id"], tz_name))
        self.rows[row["id"]]["ended_at"] = None

    def calendar_state(self, started_ats=()):
        return CalendarState(
            "UTC", self.can_edit, {k: dict(v) for k, v in self.rows.items()}
        )

    def moods(self):
        return MOODS

    def atmosphere(self):
        return {
            "mood": self.mood["id"],
            "mood_label": self.mood["label"],
            "tagline": "",
        }

    def set_mood(self, mood_id):
        self.calls.append(("set_mood", mood_id))
        name = next(m["name"] for m in MOODS if m["id"] == mood_id)
        self.mood = {"id": mood_id, "label": name}

    def clear_mood(self):
        self.calls.append(("clear_mood",))
        self.mood = {"id": None, "label": None}


class FakeStore:
    entry = "pluralspace/test"

    def __init__(self, profile):
        pass

    def exists(self):
        return False
