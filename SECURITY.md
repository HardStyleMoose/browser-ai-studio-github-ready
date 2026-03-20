# Security Policy

Version: 2026-03-20

## Supported Versions

Security fixes are intended for:

- the current main branch
- the latest packaged installer and application build produced from this repository

Older builds, stale forks, and modified redistributions may not receive fixes.

## Reporting A Vulnerability

Do not open a public issue for an unpatched security vulnerability.

Preferred reporting path:

1. Use the repository's private security advisory or private vulnerability reporting feature if available.
2. If that is not available, contact the maintainer directly through the repository owner profile or another direct maintainer contact channel.

Please include:

- a clear description of the issue
- affected version or commit
- reproduction steps
- expected and actual behavior
- any proof-of-concept artifacts needed to confirm the issue safely

## Disclosure Expectations

- Provide reasonable time for the maintainer to reproduce and address the issue before public disclosure.
- Avoid accessing data, accounts, systems, or services you do not own or have permission to test.
- Do not include live secrets, personal data, or unauthorized third-party data in public reports.

## Security Boundaries And Defaults

- API credentials should be provided through environment variables, not stored directly in app settings.
- The managed `n8n` runtime is intended to remain local-only by default.
- Provider endpoints should use `https://` unless they are explicit local loopback endpoints.
- Browser, OCR, replay, and evidence features may process local screenshots, DOM text, logs, and generated artifacts; treat those outputs as potentially sensitive.

## Secret Handling Rules

- Never commit API keys, access tokens, cookies, passwords, or session secrets to the repository.
- Use `.env`, environment variables, or your platform's secret-management tooling outside the repo.
- Treat exported logs and diagnostics as reviewable artifacts and redact sensitive fields before sharing.

## Hardening Expectations

- Keep dependencies reviewed and updated through the project's security automation and dependency review process.
- Verify packaged payload integrity before installation or redistribution.
- Review third-party license and notice requirements before distributing new builds.

## Non-Goals Of This Policy

This policy does not provide legal advice, an SLA, or a guarantee that every issue will be fixed on a specific schedule.
