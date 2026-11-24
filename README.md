> 🚧 **Status: active development.** It works for the author; interfaces may change.

# first-issue-radar

[Türkçe README](README.tr.md)

A small local web app that searches GitHub for open, unassigned issues that are good entry points for a first contribution (`good first issue`, `first-timers-only`, and `documentation` + `help wanted`), lets you pick one, and then checks the live details: description, a bounded number of comments, related open pull requests, the contributing guide location and the license. It is strictly read-only: it never creates issues or pull requests, never comments, and never downloads or runs the code of the projects it lists.

The interface is in Turkish; this README is in English.

## Why

Finding a contribution that is still free, not already taken by an open pull request, and in a project that welcomes outsiders takes many tabs. This tool does the first sweep and shows what it could *not* verify instead of guessing.

## Quick start

Requirements: **Windows** (the single-instance lock uses `msvcrt`), Python 3 (standard library only; developed on 3.12) and the [GitHub CLI](https://cli.github.com/) (`gh`), already signed in with `gh auth login`.

```bat
baslat.cmd
```

or, from a terminal in this folder:

```sh
python -B -X utf8 server.py
```

The app opens your browser on `127.0.0.1` at a random port and keeps running while the window is open (Ctrl+C in that window stops it). Your selection is kept in `data/radar.sqlite`.

## Optional configuration

The side panel can track one pull request of yours (state, checks, and whether it shows on your profile contribution graph). Copy `config.example.json` to `config.json` and edit it, or use environment variables, which win over the file:

| Setting | Environment variable | Meaning |
|---|---|---|
| `github_login` | `RADAR_GITHUB_LOGIN` | Optional. If set, the `gh` account must match it, otherwise the account is reported as untrusted. |
| `tracked_pr` | `RADAR_TRACKED_PR` | Optional. `owner/repo#number`. Without it the side panel says no PR is configured. |

## Tests

```sh
python -X utf8 -m unittest -v test_radar
```

25 tests, 24 run offline with mocked GitHub calls (1 live test is skipped by default). The live, read-only test needs your `gh` login and network: `RADAR_LIVE=1 python -X utf8 -m unittest -v test_radar.Live` (Git Bash syntax).

## Security notes

- The server listens on `127.0.0.1` only, checks the `Host` and `Origin` headers, requires a per-run token for POST requests and limits request size. The token protects against cross-site requests from a browser; it is **not** a boundary against other programs running as you on the same machine.
- Only a fixed set of read-only GitHub routes is allowed; the single GraphQL query is fixed and cannot be supplied by a client.
- The `gh` login and its permissions are never modified.

## Limits and unverified claims

- The scan runs three bounded searches (20 results each); it does not cover all opportunities. Results are marked "partial" when GitHub reports incomplete results.
- No scoring or effort estimate exists yet; results show "Puanlanmadı" (not scored).
- A project's AI/contribution policy is **not** analysed; it is shown as unknown.
- "Visible on profile" for the tracked pull request is unknown when GitHub does not return a complete answer.
- Windows only; tested on Windows with Python 3.12 and `gh` 2.x.

## License

Apache-2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
