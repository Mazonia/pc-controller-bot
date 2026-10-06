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

---

## 🛡️ Built-in Security Controls

PC Remote Sentinel implements multiple layers of defense-in-depth protection:

1. **Intruder Detection & Alerting**:
   - Any message or button interaction from an unauthorized Telegram account is rejected instantly.
   - Authorized owners receive an immediate alert containing the intruder's ID, username, and timestamp.
   - Built-in rate limiting prevents notification flood attacks.

2. **Credential & Secret Protection**:
   - Terminal command execution via `/cmd` strictly blocks inspection of `.env` and credential files.
   - Bot API tokens are automatically masked from all terminal command output and logs.

3. **Path Traversal & File Access Isolation**:
   - All incoming file drops are restricted to `downloads/` with strict basename sanitization.
   - Remote file fetching (`/get`) explicitly blacklists credential, SSH, registry, and configuration files (`.env`, `id_rsa`, `sam`, `.git`, etc.).

4. **Hardware Concurrency Locks**:
   - Webcam and screen recording operations use asynchronous locks to prevent race conditions or device lock-up.

