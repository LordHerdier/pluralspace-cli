# Roadmap

Pluralspace-cli (`plsp`) is pre-alpha and is unofficial. It currently drives
Pluralspace's web session and its Inertia endpoints, NOT a public API, so it can
break if the site changes. Until the repo has a tagged release, anything here
can change!

Priorities:

1. **Do not damage anyone's live data.** This is the basic rule. Fronting
   history and member data are system's actual records. A bug in this tool MUST
   NOT be able to rewrite them. I sure as heck wouldn't want our own data being
   corrupted.
2. **Fail loudly and _safely_ when the site changes.**
3. **Be stable and boring to install and upgrade.**

Once these three are satisfied, _only then_ will more features be added.

<details>
<summary> <h2><b>First: Protect live data [DONE]</b></h2></summary>

Every write the CLI makes is `switch`, `end`, and `mood`. All of them act on the
real account with no undo, so they need to be properly safeguarded.

- [x] **Require exact Names/IDs on writes.** `resolve_member` accepts a fuzzy
      search hit, so `plsp switch Al` can front "Alex". Writes should require an
      exact name or ID match, but fuzzy matching can stay for reads.

- [x] **Make `--dry-run` useful and universal.** On `switch`, `end` and
      `mood`, it prints a readable diff against the current state (who starts,
      ends, keeps their start time, or changes type; or the old -> new mood)
      instead of the raw request body. Still to do: `--json` output for dry
      runs. (A type change does not keep the start time: the old front ends and
      a new one starts. The dry run now says so.)

- [x] **Make replace-vs-add hard to hit by accident.** `switch` currently
      replaces the whole front set unless `--add` is passed. We either need a
      confirmation or a explicit flag (`--replace`).

- [x] **Record the previous state.** Save the prior front/mood to
      `$XDG_STATE_HOME/pluralspace/<profile>.last-state.json` and add
      `plsp undo`. Undo reopens the original front row, so the original start
      time and comment are restored. Undo re-reads and checks its own result,
      as do `switch`, `end` and `mood` (see below).

- [x] **Verify writes.** `_mutate` still treats any 200/204/302/303 as a
      success (it can't know more), so `switch`, `end` and `mood` now re-read
      the state afterwards and exit 2 with what differs if it isn't what was
      asked for: wrong or missing fronters, a kept fronter whose start time
      changed, or a mood that didn't take. The re-read state is still saved
      for `plsp undo`, so a bad write can be rolled back.

- [x] **Handle a 409 version mismatch on mutations.** `_mutate` now refreshes
      the Inertia version and retries once, like `page()`. Every write except
      `delete_front` sends full desired state, so a replay can't double-apply;
      `delete_front` refuses to replay and says the outcome is unknown.

- [x] **Document the `--add` race.** `--add` reads the current fronts and writes
      the full set. A change made in the app in between is overwritten. The
      README now states the race condition.

</details>

## Next: fail safely when the site changes

- [x] **Validate response shapes.** `schema.py` checks the fields each command
      reads (current fronts, calendar rows, members, moods, front types, the
      mood atmosphere, Inertia envelope). A mismatch raises one error, "Pluralspace's
      response changed. Please update plsp or open an issue.", naming the
      first bad path (e.g. `currentFronts[0].member_id: missing`) and exits 2.
      Every read a write depends on is checked before the write is sent.

- [x] **Flag when the site has been updated.** `/login` returns the page's
      Inertia asset `"version"` hash, which changes whenever the frontend is
      rebuilt. The last-seen version is stored per profile
      (`<profile>.site-version`, next to the cookie file) and `plsp login`
      warns on stderr when it differs. Still to do: use the hashed Vite
      filenames (`/build/assets/Dashboard-*.js`, etc.) to say _which_ page
      changed.

- [ ] **Read-only mode.** An env var or a `--read-only` flag to refuse mutations
      should be added. Useful for scripts and testing.

- [ ] **Offline client tests.** Fake the HTTP layer and cover login, session
      expiry and re-login, XSRF handling, 409 handling, and `_mutate` success +
      failure paths. Should also add recorded, scrubbed fixtures for each
      endpoint to test against and surface breakage (distinct from `*.har` files
      since those contain live creds)

- [ ] **Auditing.** Confirm that `--debug` and error paths _never_ print
      cookies, XSRF tokens, or passwords, then add a test for it.

- [ ] **Harden the cookie jar.** Write it atomically with 0600 from the
      beginning. Handle corruption or half-written cookies by starting a fresh
      session without incurring a crash.

## Ship it and make it reliable

- [x] **Add a LICENSE.**

- [x] **CI.** The usual Github Actions with `pytest` on Python 3.9 through the
      latest release. Also add a `nix flake check` since nix is a thing.

- [ ] **Cut `v0.1.0`.** Tag it, write a _good_ changelog
      [keepachangelog](https://keepachangelog.com/en/1.1.0/), state clearly and
      plainly that this is alpha software and can modify real account data. Keep
      `pyproject.toml` and the tag in sync. Tell users to pin to a tag rather
      than the repo `main`.

- [ ] **Issue and PR templates.** Basic "what did the site return?" and tell
      them to paste the `--debug` output (scrubbed).

- [ ] **Define the stability promise.** Anything before 1.0 gurantees nothing,
      but from 0.1 on we should document which parts are stable and which
      aren't.

## After all that

- [ ] **More credential backends.** I love `pass`, but most people don't. Add
      Keyring, macOS Keychain, Secret Service, and an env-var option
      (CI/containers).

- [ ] **Move to API tokens** once Pluralspace ships the public API. Should make
      our life easier and the project more stable.

- [ ] **Packaging.** A PyPi release and `pipx` instructions. Probably hold off
      on nixpkgs until the public API ships.

- [ ] **Shell completions.** It's just nice to have. A man page and a better
      `--help` menu will be added as well.
