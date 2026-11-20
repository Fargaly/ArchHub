<div align="center">
  <img src="01.APP/nodelang/data/website/favicon.svg" alt="ArchHub Logo" width="120" />
  <h1>ArchHub</h1>
  <p><b>Visual node workspace where people and AI agents wire workflows across Revit, AutoCAD, Excel, PDFs, and desktop tools.</b></p>
  <p>
    <a href="https://github.com/Fargaly/ArchHub/releases/latest"><img src="https://img.shields.io/github/v/release/Fargaly/ArchHub?style=flat-square&color=black" alt="Latest Release" /></a>
    <a href="https://archhub.io"><img src="https://img.shields.io/badge/Website-archhub.io-black?style=flat-square" alt="Website" /></a>
  </p>
</div>

<br />

ArchHub is a provider-agnostic visual node application where you can wire parametric workflows that coordinate desktop software, data, and leading AI models. Instead of typing into a chatbox, you drop agents (Claude Code, Codex, Cursor, OpenCode, Gemini CLI, Copilot, Goose/BABOOM) onto a canvas, wire them to desktop files or applications, and orchestrate complex tasks with human-in-the-loop Approve cards.

> **Local-first**: Everything is saved as `.archhub` files that you own, share, and run locally.

<img src="01.APP/nodelang/data/website/og.png" alt="ArchHub Canvas Preview" width="100%" />

---

## What you can do

- **Visual Parametric Nodes**: Wire together everything from basic file processing to deep integrations with Revit and AutoCAD. The entire app is parametric—pure nodes resolve instantly, while effect nodes run when triggered.
- **Provider-Agnostic AI Agents**: Mix and match the best tools for the job. Drop Claude, Gemini, or local models onto the canvas and wire their outputs to your host programs.
- **Human-in-the-Loop Execution**: Effect nodes pause for your explicit approval, making it safe to automate edits across your files and desktop apps.

## Download & Install

Download the latest version for Windows from our releases page:

👉 **[Download Latest Installer](https://github.com/Fargaly/ArchHub/releases/latest)**

For documentation and starter guides, visit [archhub.io](https://archhub.io).

## Quick start from source

ArchHub is built with a clean separation of concerns. To run the desktop app from source:

1. Clone the repository:
   ```bash
   git clone https://github.com/Fargaly/ArchHub.git
   ```
2. Navigate to the desktop application source:
   ```bash
   cd ArchHub/01.APP/nodelang
   ```
3. Read the [Source Documentation](04.DOCS/README.md) for environment setup and commands.

### Repository Structure

- **[01.APP/nodelang](01.APP/nodelang/)** — Desktop source code
- **[06.CLOUD/cloud_backend](06.CLOUD/cloud_backend/)** — Cockpit and cloud backend services
- **[03.TOOLS](03.TOOLS/)** — Build, installer, compiler tools, and the website exporter
- **[02.TESTS](02.TESTS/)** — Automated test suite
- **[05.EVIDENCE](05.EVIDENCE/)** — Cryptographic and build evidence

## Documentation & Contributing

- [Contribution Guidelines](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [ArchHub license and commercial use](LICENSE.md)
- [Node Catalogue Reference](04.DOCS/CATALOGUE.md)
- [Desktop App Source Documentation](04.DOCS/README.md)

### Important Links

<!-- PUBLIC LINKS:BEGIN -->
- **GitHub repository**: [https://github.com/Fargaly/ArchHub](https://github.com/Fargaly/ArchHub)
- **Latest release**: [https://github.com/Fargaly/ArchHub/releases/latest](https://github.com/Fargaly/ArchHub/releases/latest)
- **Website**: [https://archhub.io](https://archhub.io)
- **Getting started**: [https://archhub.io/docs/getting-started/](https://archhub.io/docs/getting-started/)
- **Community**: [https://archhub.io/community/](https://archhub.io/community/)
- **BABOOM**: [https://baboom.archhub.io](https://baboom.archhub.io)
- **Report a problem**: [https://github.com/Fargaly/ArchHub/issues](https://github.com/Fargaly/ArchHub/issues)
- **GitHub Discussions**: [https://github.com/Fargaly/ArchHub/discussions](https://github.com/Fargaly/ArchHub/discussions)
- **Font licence**: [https://openfontlicense.org](https://openfontlicense.org)
- **JetBrains Mono source**: [https://github.com/JetBrains/JetBrainsMono](https://github.com/JetBrains/JetBrainsMono)
<!-- PUBLIC LINKS:END -->
