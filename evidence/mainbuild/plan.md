MAINBUILD: adapt existing release admission; retain all whole-tree checks.
1. Replay immutable first-parent commits with each author/Intent/Why; existing compiler checks per delta.
2. Reuse Gemini settings_target owner; no baseline changes.
3. Delete only proven MAINREL root additions.
4. Targeted build/ratchet courts, strict staged gate, final build.py, independent review, patch+hash+commit.
Prior art: Bors merged-sequence admission; Betterer monotonic whole-tree ratchet.
