# Security Policy

## Supported version

Security fixes are applied to the latest release on the default branch. This
project is an early-stage local research tool, not a hardened network service.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or leaked credential.
Use GitHub's **Security** tab and select **Report a vulnerability** to create a
private security advisory:

<https://github.com/ABCLDZ/traceable-research-pipeline/security/advisories/new>

Include the affected version, reproduction steps, expected impact, and any
suggested mitigation. Do not include live API keys or confidential source
documents.

## Security boundary

- Treat fetched documents and model output as untrusted input.
- Use domain allowlists for tightly scoped research.
- Do not expose the fetcher as a public URL-fetching service. The URL checks
  reduce common local/private-address mistakes but are not a complete hostile
  network sandbox or DNS-rebinding defense.
- Live extraction sends selected parsed source chunks to the configured
  DeepSeek-compatible API endpoint. Review provider terms and data handling
  requirements before submitting confidential material.
- Keep runtime data, provider credentials, and frozen releases outside the
  public repository.
- Treat successful release verification as an internal consistency and byte
  integrity check. It does not authenticate a source publisher or certify that
  a source or research conclusion is true.
