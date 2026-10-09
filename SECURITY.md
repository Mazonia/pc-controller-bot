# Security Policy

## Supported Versions

Only the latest commit on the `main` branch is actively supported with security updates.

| Version / Branch | Supported          |
| ---------------- | ------------------ |
| `main`           | :white_check_mark: |
| Older releases   | :x:                |

---

## 🔒 Reporting a Vulnerability

We take the security of **PC Remote Sentinel & Multi-PC Fleet Commander** seriously. If you discover a security vulnerability, please report it responsibly rather than opening a public issue on GitHub.

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

1. **Protect your Telegram Bot Token**: Anyone with access to your bot token can control your bot. Never share it or commit it to public repositories.
2. **Configure `AUTHORIZED_USER_IDS`**: Always set your numeric Telegram ID in `.env` and `deploy_config.env`. Unlisted users are automatically rejected and logged.
3. **Keep Live Config Files in `.gitignore`**: The files `.env`, `deploy_config.env`, and `fleet.json` contain active secrets and must remain in `.gitignore`. Use the provided `.example` files as public templates.
4. **Choose a Strong `FLEET_SECRET`**: Set a long, random string for `FLEET_SECRET` to ensure your cross-network relay packets cannot be decrypted or forged.

---

## 🛡️ Built-in Security Controls

PC Remote Sentinel implements defense-in-depth security mechanisms:

### 1. Cryptographic Relay Security (AES-256-GCM)
- All remote telemetry, heartbeats, and commands transmitted across the Cloud Relay are encrypted using **AES-256-GCM** with a 12-byte random cryptographic nonce generated per message.
- Cryptographic verification tags ensure that message payloads cannot be tampered with in transit.
- **Topic Hashing**: MQTT topic paths are derived from `SHA-256(FLEET_SECRET)` to prevent eavesdropping or topic enumeration on public brokers.

### 2. Intruder Detection & Alerting
- Any message, callback query, or button interaction from an unauthorized Telegram account is rejected instantly.
- Authorized owners receive an immediate notification alert containing the intruder's numeric Telegram ID, username, and attempted action.
- Built-in cooldown timers prevent notification flooding.

### 3. Credential & Secret Protection
- Terminal command execution via `/cmd` strictly blocks inspection of `.env`, `deploy_config.env`, and credential files.
- Telegram Bot API tokens are masked automatically from terminal stdout, stderr, and logs.

### 4. Path Traversal & Isolation
- Incoming file drops are restricted to the local `downloads/` directory with strict basename sanitization.
- Remote file fetching (`/get`) blacklists sensitive system, SSH, registry, SAM, and git configuration files (`.env`, `id_rsa`, `sam`, `.git`, etc.).

### 5. Hardware Concurrency Protection
- Camera and screen recording routines utilize mutex locking to prevent hardware race conditions or device driver crashes.
