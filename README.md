# Pluralspace CLI

Command Line Interface for [Pluralspace](https://pluralspace.app).

> **Unofficial and experimental.** Pluralspace's public API isn't released yet,
> so this drives the web app's own session and [Inertia](https://inertiajs.com)
> endpoints. Expect breakage when the site changes. Once API tokens ship, the
> client will move over to them. I'm just a terminal-junkie, so I wanted this a
> bit early >:3

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

| Command                                                             | What it does                       |
| ------------------------------------------------------------------- | ---------------------------------- |
| `members [-q TEXT] [--archived] [--fronting] [--json]`              | List members                       |
| `member NAME [--history N] [--full] [--json]`                       | Show one member's profile          |
| `fronting` (alias `who`) `[--json]`                                 | Show who is fronting now           |
| `history [--month YYYY-MM] [--json]`                                | Front history for a month          |
| `switch NAME[:TYPE]... [--add] [-c COMMENT] [--silent] [--dry-run]` | Set the current front              |
| `end`                                                               | End all fronts                     |
| `mood [NAME] [--list] [--clear] [--json]`                           | Show, set or clear the system mood |

Global flags: `--profile NAME`, `--debug` (print request status codes).

### Names and IDs

Members are matched by display name, case-insensitively. Names aren't unique, so
an ambiguous name stops with an error listing the candidates; use the ID suffix
that `members` prints (`5a1925c1`) or a full ID instead.

### Switching

`switch` **replaces** the whole front set; pass `--add` to keep the current
fronters. Append `:TYPE` to give a member a front type by name or slug. The
default is `Front`.

```
plsp switch Briar                      # only Briar fronts
plsp switch Briar --add -c "tired"     # add Briar to whoever is fronting
plsp switch 5a1925c1:co-front Mari     # Ada (by id) as Co-Front, Mari as Front
plsp switch Briar --dry-run            # print the request, change nothing
```

Fronters already in the new set keep their original start time.

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
- `src/pluralspace/cli.py`: argument parsing and output

Endpoints were worked out from browser HAR captures. Keep captures out of git:
they contain live session cookies, and `*.har` is already in `.gitignore`.
