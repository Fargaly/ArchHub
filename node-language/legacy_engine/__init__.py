"""The superseded engine, kept whole and kept out of the way.

`node_lang.py` is the earlier node language; the kernel of record is
`nodelang/`. SPEC.md admits one persisted semantic shape, so a second
engine cannot sit beside the first as if both were current. Nothing here
is imported by `nodelang/`; this package depends on nothing outside
itself, which is why it could be moved in one piece.
"""
