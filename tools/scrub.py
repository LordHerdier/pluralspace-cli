"""Scrub recorded Pluralspace responses so they are safe to commit.

Standard library only, so the unit tests can import it without Playwright.

The recorder keeps raw exchanges in memory, runs them all through one
`Scrubber`, and only then writes anything. The scrubber:

- swaps every id (UUID/ULID) for a stable pseudonym, in values, in dict keys
  (`fronters` is keyed by member id) and in paths;
- replaces private text (names, descriptions, comments, avatars...) by key,
  keeping a value only if it is in `keep` (front type names are system config);
- removes the login email, password, cookie values and CSRF tokens wherever
  they appear;
- then `find_leaks` re-checks the *output* for anything it replaced, so a
  private value hiding in a key we did not think of fails the run instead of
  being committed.
"""

import html
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
ULID_RE = re.compile(r"\b[0-7][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{25}\b")
URL_RE = re.compile(r"https?://[^\s\"'<>\\]+")
QUERY_RE = re.compile(r"([?&]q=)[^&\"'\s#]+")
PAGE_RE = re.compile(r'(<script[^>]*data-page="app"[^>]*>)(.*?)(</script>)', re.DOTALL)
TITLE_RE = re.compile(r"(<title[^>]*>)(.*?)(</title>)", re.DOTALL | re.IGNORECASE)
CSRF_META_RE = re.compile(
    r'(<meta[^>]*name="csrf-token"[^>]*content=")[^"]*(")', re.IGNORECASE
)

# Keys whose string values are private text. Anything ending in "name" counts
# too (display_name, system_name, ...).
PRIVATE_KEYS = {
    "body",
    "content",
    "html",
    "initials",
    "message",
    "question",
    "subject",
    "text",
    "thought",
    "title",
    "avatar",
    "avatar_url",
    "banner",
    "bio",
    "comment",
    "description",
    "email",
    "handle",
    "image",
    "image_url",
    "nickname",
    "note",
    "notes",
    "phone",
    "pronouns",
    "slug",
    "tagline",
    "username",
    "display_label",
}
PROSE_KEYS = {
    "body",
    "bio",
    "comment",
    "content",
    "description",
    "html",
    "message",
    "note",
    "notes",
    "question",
    "subject",
    "text",
    "thought",
    "title",
}
SECRET_KEYS = {
    "auth",  # broadcast channel signature "app_key:hmac"
    "password",
    "password_confirmation",
    "token",
    "_token",
    "csrf_token",
}
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}")
SOCKET_RE = re.compile(r"(socket_id=)[\d.]+")
WORD_MIN = 3  # shorter private values ("Bo") would match everywhere


def is_private_key(key: str) -> bool:
    key = key.lower()
    return key in PRIVATE_KEYS or key.endswith(("name", "_html"))


class Scrubber:
    def __init__(self, base_url: str, secrets: Iterable[str] = ()):
        self.host = re.sub(r"^https?://", "", base_url).split("/")[0]
        self.secrets: Set[str] = set()
        for s in secrets:
            self.add_secret(s)
        self.keep: Set[str] = set()
        self._ids: Dict[str, str] = {}
        self._alias: Dict[Tuple[str, str], str] = {}
        self._counts: Dict[str, int] = {}
        self._urls: Dict[str, str] = {}
        self.originals: Set[str] = set()  # private text we replaced
        self.url_originals: Set[str] = set()  # outside URLs we replaced
        self.origin: Dict[str, str] = {}  # value -> key path it was found at
        self._by_value: Dict[str, str] = {}  # lowercased private text -> alias
        self.warnings: Set[str] = set()  # things to eyeball, not fatal
        self._word_cache: Tuple[int, Any, Any] = (-1, None, None)

    # -- inputs -----------------------------------------------------------

    def add_secret(self, value: str) -> None:
        if value:
            self.secrets.update({value, unquote(value)})

    def collect_keep(self, value: Any, keys: Tuple[str, ...] = ()) -> None:
        """Remember front type names/slugs: system config, not private."""
        if isinstance(value, dict):
            in_type = bool(keys) and keys[-1] in (
                "frontTypes",
                "subsystemFrontTypes",
                "front_type",
            )
            for k, v in value.items():
                if in_type and k in ("name", "slug") and isinstance(v, str):
                    self.keep.add(v)
                self.collect_keep(v, keys + (k,))
        elif isinstance(value, list):
            for v in value:
                self.collect_keep(v, keys)

    # -- replacement ------------------------------------------------------

    def _next(self, kind: str) -> int:
        self._counts[kind] = self._counts.get(kind, 0) + 1
        return self._counts[kind]

    def _id(self, value: str) -> str:
        if value not in self._ids:
            n = self._next("id")
            if UUID_RE.fullmatch(value):
                self._ids[value] = f"00000000-0000-4000-8000-{n:012d}"
            else:
                self._ids[value] = str(n).rjust(26, "0")
        return self._ids[value]

    def _category(self, keys: Tuple[str, ...]) -> str:
        lowered = [k.lower() for k in keys]
        if any("mood" in k for k in lowered):
            return "Mood"
        if lowered and (lowered[-1] in PROSE_KEYS or lowered[-1].endswith("_html")):
            return "Text"
        if lowered and lowered[-1] in ("avatar", "avatar_url", "image", "image_url"):
            return "Image"
        if lowered and lowered[-1] == "email":
            return "User"
        if lowered and lowered[-1] == "slug":
            return "slug"
        return "Member"

    def _aliased(self, category: str, value: str, keys: Tuple[str, ...] = ()) -> str:
        key = (category, value)
        if key not in self._alias:
            n = self._next(category)
            self.originals.add(value)
            self.origin.setdefault(value, ".".join(keys) or "?")
            if category == "User":
                self._alias[key] = f"user{n}@example.invalid"
            elif category == "Image":
                self._alias[key] = f"https://example.invalid/image-{n}.png"
            elif category == "slug":
                self._alias[key] = f"slug-{n}"
            else:
                self._alias[key] = f"{category} {n}"
            self._by_value.setdefault(value.lower(), self._alias[key])
        return self._alias[key]

    def _words(self):
        """(regex over every private value learned so far, regex over aliases).
        Whole words only: replacing inside words turns ordinary values like
        "archived" into nonsense when some private value happens to be a
        fragment of them."""
        version = len(self._by_value)
        if self._word_cache[0] != version:
            keep = {k.lower() for k in self.keep}
            usable = [
                v
                for v in self._by_value
                if len(v) >= WORD_MIN
                and any(c.isalpha() for c in v)
                and not v.startswith("http")
                and v not in keep
            ]
            parts = [
                rf"(?<!\w){re.escape(v)}(?!\w)"
                for v in sorted(usable, key=len, reverse=True)
            ]
            aliases = sorted(set(self._by_value.values()), key=len, reverse=True)
            self._word_cache = (
                version,
                re.compile("|".join(parts), re.IGNORECASE) if parts else None,
                re.compile("|".join(map(re.escape, aliases))) if aliases else None,
            )
        return self._word_cache[1], self._word_cache[2]

    @staticmethod
    def _prose(s: str) -> bool:
        """Several words. Single tokens are enum values, ids and paths: they are
        replaced by key only, never by matching, so "archived" stays "archived"."""
        return " " in s.strip()

    def text(self, s: str, words: bool = False) -> str:
        """Scrub free text: secrets, ids, outside URLs and search terms. With
        `words`, also swap any private value learned elsewhere for its alias."""
        for secret in sorted(self.secrets, key=len, reverse=True):
            s = s.replace(secret, "[redacted]")
        s = UUID_RE.sub(lambda m: self._id(m.group(0)), s)
        s = ULID_RE.sub(lambda m: self._id(m.group(0)), s)
        s = QUERY_RE.sub(r"\1query", s)
        s = SOCKET_RE.sub(r"\g<1>0.0", s)

        def url(m):
            if m.group(0).split("/")[2:3] == [self.host]:
                return m.group(0)
            self.url_originals.add(m.group(0))
            self._urls.setdefault(
                m.group(0), f"https://example.invalid/{len(self._urls) + 1}"
            )
            return self._urls[m.group(0)]

        s = URL_RE.sub(url, s)
        regex, _ = self._words()
        if words and regex and self._prose(s):
            s = regex.sub(lambda m: self._by_value[m.group(0).lower()], s)
        return s

    def value(self, value: Any, keys: Tuple[str, ...] = ()) -> Any:
        if isinstance(value, dict):
            return {self.text(k): self.value(v, keys + (k,)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(v, keys) for v in value]
        if isinstance(value, str) and keys:
            key = keys[-1].lower()
            if key in SECRET_KEYS and value:
                return "[redacted]"
            if (
                is_private_key(key)
                and value
                and value not in self.keep
                and not HEX_RE.fullmatch(value)
            ):
                return self._aliased(self._category(keys), value, keys)
        if isinstance(value, str):
            return self.text(value, words=True)
        return value

    def path(self, path: str) -> str:
        return self.text(path)

    def body(self, text: str, content_type: str) -> str:
        """Scrub a response body: JSON, an HTML page with Inertia data, or text."""
        if "json" in content_type:
            try:
                data = json.loads(text)
            except ValueError:
                return self.text(text)
            return json.dumps(self.value(data), indent=2, ensure_ascii=False) + "\n"
        if "html" in content_type:
            return self._html(text)
        return self.text(text)

    def _html(self, text: str) -> str:
        pages: List[str] = []

        def page(m):
            try:
                data = json.loads(html.unescape(m.group(2)))
            except ValueError:
                raise ValueError("an Inertia page in the HTML does not parse") from None
            raw = json.dumps(self.value(data), ensure_ascii=False)
            pages.append(m.group(1) + html.escape(raw) + m.group(3))
            return f"\0PAGE{len(pages) - 1}\0"

        # The page data is already scrubbed and HTML-escaped: set it aside so
        # the URL and id patterns below cannot run across its &quot;s.
        text = PAGE_RE.sub(page, text)
        text = CSRF_META_RE.sub(r"\1[redacted]\2", text)
        text = TITLE_RE.sub(
            lambda m: m.group(1) + self.text(m.group(2), True) + m.group(3), text
        )
        text = self.text(text)
        for i, p in enumerate(pages):
            text = text.replace(f"\0PAGE{i}\0", p)
        return text

    # -- the final check --------------------------------------------------

    def secret_leaks(self, text: str) -> List[str]:
        """Login secrets anywhere in `text`: checked against whole files."""
        low = text.lower()
        if any(len(s) >= WORD_MIN and s.lower() in low for s in self.secrets):
            return ["a login secret"]
        return []

    def _prose_leaks(self, s: str, found: set, keys: Tuple[str, ...] = ()) -> None:
        regex, aliases = self._words()
        if not regex:
            return
        if not self._prose(s):
            # A lone token equal to a replaced value is usually an enum word
            # ("system", "default"): worth a look, not worth failing the run.
            if s.lower() in self._by_value and s not in self.keep:
                origin = self.origin.get(
                    next((x for x in self.originals if x.lower() == s.lower()), ""), "?"
                )
                self.warnings.add(
                    f"{'.'.join(keys) or '?'}: a lone value equal to one replaced at {origin}"
                )
            return
        if aliases:
            s = aliases.sub("", s)  # our own "Member 3" is not a leak
        for m in regex.finditer(s):
            o = next(
                (x for x in self.originals if x.lower() == m.group(0).lower()), "?"
            )
            where = self.origin.get(o, "?")
            found.add(f"a value replaced at {where} (length {len(m.group(0))})")

    def check_value(
        self, value: Any, found: Optional[set] = None, keys: Tuple[str, ...] = ()
    ) -> List[str]:
        """Leaks among the string *values* of scrubbed data (not its keys)."""
        found = set() if found is None else found
        if isinstance(value, dict):
            for k, v in value.items():
                self.check_value(v, found, keys + (k,))
        elif isinstance(value, list):
            for v in value:
                self.check_value(v, found, keys)
        elif isinstance(value, str):
            self._prose_leaks(value, found, keys)
        return sorted(found)

    def check_body(self, text: str, content_type: str) -> List[str]:
        """Leaks in a scrubbed body, looking only at its data and prose: a
        URL, a path or markup that merely contains a short value is fine."""
        found: set = set()
        if "json" in content_type:
            try:
                return self.check_value(json.loads(text))
            except ValueError:
                return ["JSON that does not parse"]
        if "html" in content_type:
            for m in PAGE_RE.finditer(text):
                try:
                    self.check_value(json.loads(html.unescape(m.group(2))), found)
                except ValueError:
                    found.add("page data that does not parse")
            for m in TITLE_RE.finditer(text):
                self._prose_leaks(m.group(2), found)
        return sorted(found)
