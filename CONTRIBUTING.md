# Contributing to PC Remote Sentinel & Command Center

Thank you for your interest in contributing to **PC Remote Sentinel & Command Center**! Contributions from the community help make this project more robust, reliable, and accessible.

---

## 🛠️ Code of Conduct
By participating in this project, you agree to abide by the guidelines set out in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## 🚀 How to Contribute

### 1. Reporting Issues
* Search existing GitHub Issues to see if the problem or feature request has already been reported.
* If not, open a new issue with:
  * A clear, descriptive title.
  * Precise reproduction steps.
  * Your operating system version, Python version, and dependency versions.
  * Expected vs. actual behavior, along with relevant log outputs (ensure no sensitive tokens/passwords are included).

### 2. Suggesting Enhancements
* Open an issue with the `enhancement` label.
* Describe the proposed feature, user workflow, and technical motivation.

### 3. Submitting Pull Requests
1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/Mazonia/pc-controller-bot.git
   cd pc-controller-bot
   ```
3. **Create a topic branch**:
   ```bash
   git checkout -b feature/my-cool-feature
   ```
4. **Set up virtual environment**:
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # Linux / macOS:
   source venv/bin/activate
   pip install -r requirements.txt
   ```
5. **Implement your changes**:
   * Follow PEP 8 guidelines and format cleanly.
   * Write self-explanatory code with inline documentation where needed.
   * Ensure any new configurations are documented in `.env.example` and `README.md`.
6. **Commit with descriptive messages**:
   ```bash
   git commit -m "feat: add feature description"
   ```
7. **Push to your fork and submit a Pull Request** against the `main` branch.

---

## 🛡️ Guidelines
* **Secrets & Credentials**: Never commit `.env` files, API tokens, Telegram credentials, session files, or personal media.
* **Testing**: Manually verify your bot commands using a private Telegram test bot before submitting PRs.
* **Architecture**: Keep modules decoupled: separation between Telegram UI handlers, domain logic, and external APIs.
