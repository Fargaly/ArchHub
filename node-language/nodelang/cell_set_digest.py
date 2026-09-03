"""Incremental commitment to a Cell set: the digest a signed head carries.

The v1 head digest folded every cell of the snapshot through one SHA-256
in sorted order. Sound, and O(graph) per commit: on the founder's 5.27M-cell
graph that was ~50 s to sign a pan, and ~50 s again to verify each head at
the next open. A digest that must be recomputed from scratch after every
change is a rule about the graph's size, not about its content.

v2 commits to the same set through an additive hash (Bellare-Micciancio
"AdHash"): each cell hashes to a 2048-bit integer through SHAKE-256 over
its length-prefixed fields; the set's accumulator is their sum modulo
2**2048; the digest is SHA-256 over the revision and that accumulator.
Adding a cell adds its hash, removing one subtracts it, replacing one does
both -- so a commit's digest costs the cells it changes, and stepping a
verifier back one revision costs the cells that revision wrote. The 2048-bit
modulus keeps generalised-birthday (Wagner k-sum) attacks near 2**90.

Nothing here reads a store or a snapshot, and nothing here imports the
kernel: this is a leaf the kernel and the authority both import.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

# No sibling import: universal_cell (the kernel) imports this leaf, so a
# Cell here is anything with id, link0, link1 and atom.
Cell = Any

SET_HASH_BITS = 2048
SET_HASH_BYTES = SET_HASH_BITS // 8
SET_HASH_MODULUS = 1 << SET_HASH_BITS
DIGEST_V2_PREFIX = "v2:"
_DOMAIN = b"ArchHub/universal-cell-snapshot/v2"
_CELL_DOMAIN = b"ArchHub/universal-cell/v2"


def _field(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def cell_set_hash(cell: Cell) -> int:
    """One cell's contribution to the set accumulator."""
    digest = hashlib.shake_256()
    _field(digest, _CELL_DOMAIN)
    _field(digest, cell.id.encode("utf-8"))
    _field(digest, cell.link0.encode("utf-8"))
    _field(digest, cell.link1.encode("utf-8"))
    _field(digest, cell.atom)
    return int.from_bytes(digest.digest(SET_HASH_BYTES), "big")


def set_accumulator(cells: Iterable[Cell]) -> int:
    """The accumulator of a whole set, from scratch."""
    total = 0
    for cell in cells:
        total += cell_set_hash(cell)
    return total % SET_HASH_MODULUS


def accumulator_add(accumulator: int, cells: Iterable[Cell]) -> int:
    for cell in cells:
        accumulator += cell_set_hash(cell)
    return accumulator % SET_HASH_MODULUS


def accumulator_remove(accumulator: int, cells: Iterable[Cell]) -> int:
    for cell in cells:
        accumulator -= cell_set_hash(cell)
    return accumulator % SET_HASH_MODULUS


def snapshot_digest_v2(revision: int, accumulator: int) -> str:
    """The head digest for one revision over one accumulator."""
    if type(revision) is not int or revision < 0:
        raise ValueError("revision must be a non-negative integer")
    if type(accumulator) is not int or not 0 <= accumulator < SET_HASH_MODULUS:
        raise ValueError("accumulator is outside the set-hash modulus")
    digest = hashlib.sha256()
    _field(digest, _DOMAIN)
    _field(digest, str(revision).encode("ascii"))
    _field(digest, accumulator.to_bytes(SET_HASH_BYTES, "big"))
    return DIGEST_V2_PREFIX + digest.hexdigest()


def is_v2_digest(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith(DIGEST_V2_PREFIX)
        and len(value) == len(DIGEST_V2_PREFIX) + 64
    )
