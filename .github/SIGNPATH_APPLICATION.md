# SignPath Foundation application — ArchHub

This is the ready-to-send application for SignPath's free OSS code-
signing program. Submission lands at https://signpath.org or via the
contact form on https://signpath.io/solutions/open-source-community.

When applying, paste the body below. Replace `<your name / email>`
with your real values; the rest is already correct for ArchHub as of
v0.15.x.

---

## Application body

**Project name:** ArchHub

**Repository:** https://github.com/Fargaly/ArchHub

**License:** MIT (OSI-approved, no commercial dual-licensing)

**Project type:** Windows desktop application (PyQt6)

**Maintainer:** `<your name>`, `<your email>`

**Brief description (one sentence):**
> ArchHub is an AI cockpit for architects: one chat drives Revit,
> Blender, AutoCAD, 3ds Max and Speckle, and saves working patterns as
> copy-paste shareable Skills.

**Why we need code signing:**
Windows SmartScreen flags every unsigned installer download with a
"Windows protected your PC" warning, which an estimated 80% of users
will not click through. ArchHub is a free open-source desktop app that
needs to reach individual architects directly via download from
GitHub Releases; signing eliminates the warning, builds trust, and is
a hard requirement for distribution to Windows-managed corporate
machines under standard execution-policy restrictions.

**Compliance with SignPath Foundation conditions:**

| Requirement | Status |
|---|---|
| OSI-approved license, no commercial dual-licensing | ✅ MIT |
| No proprietary or non-OSS components | ✅ All dependencies are MIT/Apache/BSD; no closed source bundled |
| Not malware or PUP | ✅ |
| Actively maintained | ✅ Tags `v0.10.0` … `v0.15.0` shipped within the last week; daily commits on `main` |
| Released form ready for signing | ✅ Inno Setup `.exe` installer published as a release asset on every `v*.*.*` tag (e.g., https://github.com/Fargaly/ArchHub/releases/tag/v0.15.0) |
| Functionality described on download page | ✅ See https://github.com/Fargaly/ArchHub#what-it-does and https://fargaly.github.io/ArchHub/ |
| Verifiable build from source | ✅ The `installer/setup.iss` Inno Setup script is checked in; built by `.github/workflows/release.yml` on every tag. Anyone can audit the workflow + script and reproduce the binary on a Windows runner. |
| Manual approval per release | ✅ Releases are tag-gated. Each `v*.*.*` tag is pushed manually after local Inno Setup compile + tests pass. |
| Code-signing team = development team | ✅ Single maintainer; signing requests will originate from the same GitHub account as commits |

**Pipeline integration plan:**

We will integrate SignPath via the GitHub Actions integration
documented at https://about.signpath.io/documentation/build-system-integration/github-actions:

1. Configure SignPath project + signing policy for `Fargaly/ArchHub`
2. Add SignPath secrets to repo Actions secrets
3. Extend `.github/workflows/release.yml` to invoke
   `signpath/github-action-submit-signing-request@v1` on the produced
   `ArchHub-Setup-*.exe`
4. Re-publish the signed `.exe` as the release asset

**Contact:** `<your email>` (lead maintainer, Fargaly on GitHub)

---

## Notes (do not paste)

- SignPath's HSM holds the private key; we never see it. Each release
  build sends an artifact to SignPath's API for signing, and a signed
  binary comes back. The SignPath project policy will be set so that
  only the `Release` workflow on `main` (gated by tag pushes) can
  request signing.
- The Foundation tier is free for qualifying OSS. There is no fee, no
  HSM purchase, no subscription. Their revenue model is enterprise
  paid signing — OSS is essentially marketing.
- If SignPath rejects, fallback: Certum's free OSS Authenticode
  certificate (https://www.certum.eu/en/cert_offer_en_open_source_cs/)
  — same FIPS-140-2 HSM model, slightly more bureaucratic to get.
