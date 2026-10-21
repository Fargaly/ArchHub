# Contributing

Read [the documentation index](04.DOCS/README.md), [agent instructions](AGENTS.md), and the existing source before changing it.
Report a reproducible issue through [GitHub Issues](https://github.com/Fargaly/ArchHub/issues); keep security details private as described in [SECURITY.md](SECURITY.md).
Keep each pull request focused, preserve user data and ownership boundaries, and include the relevant checks and exact source revision.
Install Python dependencies from `requirements.txt`, then `python -m pip install --no-deps -e .` for source module entrypoints; Studio uses `npm ci` and `npm run build:studio`. Run focused Python checks with `python -m pytest -q -p no:cacheprovider` and JavaScript checks with `node --test <test-file>`.
Commits pass the product pipeline and identify their registered `Intent:` and `Why:` trailers. Release and installed-app acceptance are separate from source checks.
The repository does not currently grant a general source license; do not assume otherwise from third-party notices.
