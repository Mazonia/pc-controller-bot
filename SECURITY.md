# Security Policy

## Supported Versions

Only the latest commit on the `main` branch is actively supported with security updates.

| Version / Branch | Supported          |
| ---------------- | ------------------ |
| `main`           | :white_check_mark: |
| Older releases   | :x:                |

---

## 🔒 Reporting a Vulnerability

We take the security of **PC Remote Sentinel & Command Center** seriously. If you discover a security vulnerability, please report it responsibly rather than opening a public issue on GitHub.

### How to Report
1. Open a **Private Security Advisory** via the GitHub repository's Security tab, or contact the maintainer directly.
2. Include in your report:
   - Description of the vulnerability and attack vector.
   - Step-by-step reproduction guide or proof-of-concept (PoC).
   - Potential impact on users, hardware, or API resources.

### Response Timeline
* **Initial Acknowledgement**: Within 48 hours.
* **Assessment & Fix**: Typically within 7 business days depending on severity.
* **Public Disclosure**: Coordinated after a patched version has been deployed.

---

## ⚠️ Security Best Practices for Users
* **Never share your Telegram Bot Token**: Anyone with this token can control your bot.
* **Set Authorized User IDs**: Always restrict access using `AUTHORIZED_USER_IDS` in `.env` to prevent unauthorized parties from accessing bot functions.
* **Keep `.env` in `.gitignore`**: Never push configuration files containing live secrets to public repositories.
