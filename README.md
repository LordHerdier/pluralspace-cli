# Pluralspace CLI

[![CI](https://github.com/LordHerdier/pluralspace-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/LordHerdier/pluralspace-cli/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Command Line Interface for [Pluralspace](https://pluralspace.app). 

> **Unofficial and experimental.** Pluralspace's public API isn't released yet,
> so this drives the web app's own session and [Inertia](https://inertiajs.com)
> endpoints. Expect breakage when the site changes. Once API tokens ship, the
> client will move over to them. I'm just a terminal-junkie, so I wanted this a
> bit early >:3

<img alt="Cats dancing" src="https://64.media.tumblr.com/c08b22a167d7bf1c09f30c8770f2c541/4160be3cc2b84620-5c/s400x600/f5bd93c0608dc29a87abb3239251467ef69b722f.gifv" width=100%>

## Install

Requires Python 3.9+ and [`pass`](https://www.passwordstore.org/) with a working
GPG setup. There are no Python dependencies (standard library only). Times are
shown in your system's local timezone.

```
pip install -e .
plsp --help
```

Or run it straight from a checkout:

```
PYTHONPATH=src python3 -m pluralspace.cli --help
```

## Authentication

```
plsp login      # prompts for email/password, offers to save them to pass
plsp whoami     # show the logged-in account
plsp logout     # drop the local session (the pass entry is kept)
```

Credentials are stored in `pass` at `pluralspace/<profile>`: the password on the
first line, then the email.

```
hunter2
email: you@example.com
```

After login the session cookie is kept in
`$XDG_STATE_HOME/pluralspace/<profile>.cookies` (default
`~/.local/state/pluralspace/`, mode 0600). Sessions last about four hours; when
one expires, commands log in again from `pass` and retry automatically.

Use `--profile NAME` to keep separate accounts (`pluralspace/NAME` in pass).

## Commands

| Command                                                                                       | What it does                       |
| --------------------------------------------------------------------------------------------- | ---------------------------------- |
| `members [-q TEXT] [--archived] [--fronting] [--json]`                                        | List members                       |
| `member` (alias `m`) `NAME [--history N] [--full] [--json]`                                   | Show one member's profile          |
| `fronting` (aliases `who`, `w`) `[--json]`                                                    | Show who is fronting now           |
| `history [--month YYYY-MM] [--json]`                                                          | Front history for this month       |
| `switch` (alias `sw`) `NAME[:TYPE]... [--add\|--replace] [-c COMMENT] [--silent] [--dry-run]` | Set the current front              |
| `end [--dry-run]`                                                                             | End all fronts                     |
| `mood [NAME] [--list] [--clear] [--dry-run] [--json]`                                         | Show, set or clear the system mood |
| `undo [--dry-run] [--yes] [--no-delete] [--force]`                                            | Undo the last switch, end or mood  |

Global flags: `--profile NAME`, `--debug` (print request status codes).

### Names and IDs

Pluralspace gives each member a plain `name` and a (possibly) decorated `display_name`
(e.g. `Amanda` vs `⊹˚₊ Amanda  ₊˚⊹`). `members` shows both when they differ.

- **Writes** (`switch`, `mood`) need an **exact** match, case-insensitive, on the
  `name`, the `display_name`, or an ID (full, or the suffix `members` prints,
  e.g. `3b2a29c2`). Partial names never match; a near miss errors out and lists
  candidates. Moods likewise must match by full name.
- **Reads** (`member`) still allow fuzzy search.
- Names aren't unique, so an ambiguous name stops with an error listing the
  candidates; use the ID suffix instead.

### Switching

`switch` **replaces** the whole front set; pass `--add` to keep the current
fronters. If the switch would end anyone who is fronting, it asks for
confirmation first; pass `--replace` to skip the prompt (required when stdin is
not a terminal, e.g. in scripts). `--add` and `--replace` are mutually
exclusive, and `--dry-run` never prompts. Append `:TYPE` to give a member a front type by name or slug. The
default is `Front`.

```
plsp switch Briar                      # only Briar fronts (asks first)
plsp switch Briar --replace            # same, no prompt
plsp switch Briar --add -c "tired"     # add Briar to whoever is fronting
plsp switch 5a1925c1:co-front Mari     # Ada (by id) as Co-Front, Mari as Front
plsp switch Briar --dry-run            # show who starts/ends/keeps, change nothing
```

Fronters already in the new set keep their original start time and comment, as
long as their type doesn't change. Changing a fronter's type ends their front and
starts a new one, so the start time resets (the dry run says so).

**`--add` race:** `--add` reads the current fronters and then writes the full
set back. If someone changes the front in the app between those two steps, that
change is overwritten. The window is short, but avoid `--add` while someone else
may be switching at the same time.

`--dry-run` (on `switch`, `end` and `mood`) fetches the current state and prints
a diff instead of writing anything: `+ start`, `- end`, `= keep` (with the
original start time) and `~ retype` for each fronter, or `mood: old -> new`.

### Undo

Before every `switch`, `end` and `mood` that changes something, `plsp` saves the
previous state to `$XDG_STATE_HOME/pluralspace/<profile>.last-state.json` (mode
0600). `plsp undo` restores it. Only the most recent write is kept, and a write
that changes nothing (or a `--dry-run`) leaves the saved state alone.

```
plsp undo --dry-run    # show what it would do, change nothing
plsp undo              # asks to confirm; --yes skips the prompt
plsp undo --no-delete  # end the new fronts instead of deleting them
```

- **Fronts** come back on their _original_ front, so the original start time and
  comment are kept (the time zone of your Pluralspace account is respected).
- Fronts that write **started** are **deleted** from the history, so undo leaves no
  short entries behind. Only a `switch` starts fronts, and a front is only
  deleted if it is still exactly as it was saved, started around that write, and
  under an hour old. Anything else that is live (started in the app since, or
  edited) is ended, not deleted.
- **Deleting can't be undone.** The dry run and prompt list every deletion, and
  after an undo that deleted something there is nothing to redo. With
  `--no-delete` the new fronts are ended instead (leaving short entries), and
  running `plsp undo` again redoes the first one.
- Because the original front is reopened, the time between it ending and the
  undo counts as fronting. Undo is for catching a mistake soon after; if the front
  ended more than an hour ago it needs `--force`.
- It **refuses** if a saved front has been deleted or edited in the app since, or
  if the account can't edit fronts, and `--force` does not override that.
- It needs **`--force`** if fronts or the mood have changed since the write
  (made in the app, or by another command), since undoing would overwrite that.
- Afterwards it re-reads the site and reports an error if the result isn't what
  was expected, rather than assuming the write worked.

## Acknowledgements

Thank you so much to [@SiteRelEnby](https://github.com/SiteRelEnby) for their [simplyplural-cli](https://github.com/SiteRelEnby/simplyplural-cli) that I took inspiration for this project from. If you used their tool, this will feel right at home!

## Development

```
pip install -e '.[dev]'
pytest
```

The layout:

- `src/pluralspace/credentials.py`: the `pass` backend
- `src/pluralspace/api_client.py`: cookie session, XSRF and Inertia requests
- `src/pluralspace/fronts.py`, `undo.py`, `state.py`, `timeutil.py`: pure planning
  for switches and undo, and the saved-state file
- `src/pluralspace/cli/`: argument parsing, one module per group of commands
- `tools/`: dev-only helpers, e.g. `record_fixtures.py` records scrubbed site
  fixtures with Playwright (see [tools/README.md](tools/README.md))

Endpoints were worked out from browser HAR captures. Keep captures out of git:
they contain live session cookies, and `*.har` is already in `.gitignore`.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
