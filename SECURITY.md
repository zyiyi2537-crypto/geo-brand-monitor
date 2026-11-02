# Security Policy

## Supported versions

Security fixes are provided for the latest release on the `main` branch.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
security advisory feature for this repository. Include reproduction steps,
affected versions, impact, and suggested mitigation.

Do not access, modify, or retain data that does not belong to you while
researching a vulnerability. We will acknowledge reports within five business
days and provide updates during the investigation.

## Secrets and test data

Never commit credentials, browser profiles, session cookies, customer data, or
production database extracts. Use local environment files based on
`backend/.env.example`; real values must come from a secret manager or the
runtime environment.
