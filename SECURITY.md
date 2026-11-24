# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| latest commit on `main` | yes |
| older | no |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Report it privately with GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability**.

Include: affected version, a description, steps to reproduce, and the impact you see. Never include real tokens or personal data in a report; describe where they appear instead.

## What to expect

This is a one-person project maintained on a best-effort basis. The maintainer aims to send an initial response within **14 days**. A fix date is not promised.

## Scope

In scope: the local server (`server.py`: host, origin and token checks, request limits), the read-only GitHub access layer (`radar.py`) and the browser UI. Out of scope: weaknesses of GitHub or the `gh` tool, and attacks by other programs running as the same user on the same machine (the README states this limit).
