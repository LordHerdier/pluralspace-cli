# tools

Dev-only helpers. Nothing here ships with `plsp`, and CI doesn't run it.

## record_fixtures.py

Logs in to the real Pluralspace with Playwright, walks through what `plsp` does,
and saves every response as a **scrubbed** fixture in `tests/fixtures/site/`
for the offline client tests (see "Offline client tests" in the ROADMAP).

The login goes through the real form in a browser. The rest of the requests are
made through that browser session with the same headers and no-redirect
behaviour as `PluralspaceAPI`, so the fixtures show what the CLI really sees,
including 302/409/419 responses that a browser would hide.

### Setup

```
nix develop ./tools        # python + playwright + pinned chromium + pass
# or: pip install -r tools/requirements.txt && playwright install chromium
```

Credentials come from `PLSP_FIXTURE_EMAIL` / `PLSP_FIXTURE_PASSWORD`, or the
`pass` entry `pluralspace/testing` (`--profile NAME` to change it). **Use a
throwaway account**, not your real system.

### Scenarios

| Scenario | Writes? | Records                                                                                                                               |
| -------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `auth`   | no      | UI login, wrong password, CLI-style login, XSRF 419, stale-version 409, logout, expired session                                       |
| `reads`  | no      | dashboard, whoami, fronts, atmosphere, front types, members (search/archived/fronting/page 2/profile), calendar, moods, member search |
| `fronts` | **yes** | switch, add, retype, end one, end all, reopen, edit comment, delete (and replay), error cases                                         |
| `moods`  | **yes** | set, change, clear, unknown mood                                                                                                      |

```
python tools/record_fixtures.py                 # auth + reads
python tools/record_fixtures.py --delay 3         # slower: seconds between actions (default 1.5)
python tools/record_fixtures.py --write         # everything (asks you to type the email)
python tools/record_fixtures.py reads --headed  # one scenario, visible browser
```

The write scenarios only delete rows they created, and in a `finally` they end
everything, reopen the fronts that were live (keeping their start time) and put
the mood back. If a run is killed hard, check the app.

### Scrubbing

Raw responses stay in memory. Before anything is written they are scrubbed
(`scrub.py`, tested in `tests/test_fixture_scrub.py`):

- ids become stable pseudonyms (`00000000-0000-4000-8000-000000000001`), also in
  paths and in dict keys;
- names, descriptions, comments, avatars, emails and slugs are replaced by key
  (`Member 3`, `Mood 1`, `user1@example.invalid`); front type names are kept;
- every private value learned that way is then replaced wherever else it shows
  up in a response (first pass learns, second pass writes). Values of 5+
  characters match inside other words, shorter ones only as whole words, and
  paths/URLs/query strings are never touched;
- the login email, password, every cookie value and the CSRF token are removed;
  only `Set-Cookie` _names_ and a few headers are stored, never request headers;
- finally the output is checked: the string values in the JSON/Inertia data for
  any replaced value still present, and every file for the login secrets. If
  anything is left, the run fails and **writes nothing**. It prints the key path
  and length (never the value) so you can tell a real leak from a harmless match.

Scrubbing is by key name, so a new field holding personal text could slip
through. **Read `git diff` before committing fixtures.**
