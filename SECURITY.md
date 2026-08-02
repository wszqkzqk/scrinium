# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing **zimoliao@mail.ustc.edu.cn** with:

1. Description of the vulnerability
2. Steps to reproduce
3. Potential impact

You will receive a response within 72 hours. We will work with you to understand and address the issue before any public disclosure.

## Security Considerations

Scrinium handles:

- **API keys** (LLM, MinerU) — stored in `config.local.yaml` (git-ignored) or environment variables. Never committed to version control.
- **Local file system access** — reads/writes to `data/`, `workspace/`, and configured directories.
- **External API calls** — to Crossref, Semantic Scholar, OpenAlex for metadata; to LLM providers for text processing.

### Best Practices for Users

- Keep `config.local.yaml` out of version control (already in `.gitignore`)
- Use environment variables for API keys in CI/CD environments
- Review PDF sources before ingestion — MinerU processes PDFs locally or via `mineru-open-api` cloud requests
