# Security Policy

## Supported versions

This repository is a sanitized public case study and a small set of illustrative
code snippets. Fixes target the latest version on the `main` branch.

| Version          | Supported |
| ---------------- | --------- |
| latest (`main`)  | yes       |
| older tags       | no        |

## Reporting a vulnerability

Please do not open a public issue for security vulnerabilities.

Report privately through GitHub's
[Report a vulnerability](https://github.com/Jott2121/bow/security/advisories/new)
flow (the repository's Security and Advisories tab). I aim to acknowledge reports
within 72 hours and to ship a fix or mitigation for confirmed issues as quickly
as is practical.

When reporting, please include:

- a description of the issue and its impact,
- steps to reproduce (a minimal proof of concept if possible), and
- any suggested remediation.

## Scope

The published snippets are illustrative (resilience, scheduling, single writer
dispatch). Findings of interest include unsafe file or process handling in the
snippets and supply chain risks in CI. This repository pins its GitHub Actions to
commit SHAs and runs CodeQL and Dependabot to reduce that surface.

Thanks for helping keep it solid.
