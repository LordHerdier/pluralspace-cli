# Pluralspace CLI

Command Line Interface for Pluralspace.app

Unofficial and experimental: it drives the web app's session/Inertia endpoints
until a proper API ships.

## Auth

```
pluralspace login      # prompts once, offers to store creds in pass
pluralspace whoami     # re-logins from pass automatically if the session expired
pluralspace logout
```

Credentials are kept in `pass` at `pluralspace/<profile>` (first line password,
then `email: you@example.com`). The session cookie jar is at
`$XDG_STATE_HOME/pluralspace/<profile>.cookies` (mode 0600).
