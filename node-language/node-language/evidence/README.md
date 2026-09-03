# Node Language implementation evidence

This directory contains revision-bound generated evidence. It is not normative
architecture and cannot make a red requirement green by assertion.

Generate the current local evidence record:

```powershell
python build_current_evidence.py
```

The runner hashes the exact scoped sources, executes the listed courts, records
environment and duration, and writes `current-evidence.json`. A green command
proves only its named scope. `release_eligible` remains false while required
real-browser, one-building, persistent-attention, cloud, security, recovery,
multi-user, packaging, installer, or release courts are absent or red.
