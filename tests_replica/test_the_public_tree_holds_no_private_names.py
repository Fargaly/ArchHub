"""Court: the public tree holds none of the founder's addresses or client names.

WORKSPACE-STANDARD.md: T2/T3 material never enters a public tree. This repo
is public, so a founder mailbox, a client name or a client project code in
any tracked file is a leak. The forbidden words are kept here only as the
sha256 of their lowercase form, so this court does not publish what it
guards. Each tracked text file is split into lowercase words (letters and
digits), dotted or hyphenated word pairs, and mail addresses; a word whose
hash is on the list fails the court with the file and line.

A 64-character hash that happens to contain a client name is one word of
64 characters, so it never matches.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# sha256(lowercase word) of founder mailboxes, founder handles, client names
# and client project codes. Add a line to forbid another word.
FORBIDDEN = frozenset({
    "ebab69f6f0fd2c9718bb5037abcd7c1e6f2c549e5ebc77dc0e58cd165fe3cf73",
    "3169833dc19edd1700cc03c3b412785b77cbe8859175913fabbb1c196781e382",
    "7af1bfa6897feb2e479cab67a82b16302a3d5bd5e4740212e8f0b4d43613f3e6",
    "d4ba5d5713e3cf94e2262d89f653cb4cd808a798798d502a39ca3b00cfa04679",
    "67d3f0260d3a3f9a9c2c7f6063cba2bde8c87aca56e4476359e61bf127a0eb83",
    "d2cd7b1ba437642329c88bdcfecb0342ff1c1882ba5bf55a0349a3e26bbcf415",
    "d35ed605d54b15fe70d7dd899d7d3b84ebfa3cddc831932d95d8978b174f5b1a",
    "efc9712103fbafad36e534d8a995318a774b9f81050b9bd491db27d80b593198",
    "1ceac276f4245cdc6738549a4b4c0406eafcc3e5dd3e62ee00b55491a50a01f8",
    "dd9cd53610741bdcb911fc3036e749162ca215dde52433e1685c67980dc5a835",
    "f2079ed255818635d763653905870edad90199b3e12d1f0661c65b9e62198865",
    "f11e45aab45956fbf65b916e8c7391d535b98c3d10244e250846c29996808b1d",
    "4b8fbceba50bc3df33a55fccf26ae6093920e024bf00cdded1987c21f047f22f",
    "1a2dc261f02e40100600638910e4bd22326e14afcfa9bd193d02ff0c0f3a5a1a",
    "c52ee7b04af400c4366c737c4ecaa4cecf6b2979b0a0ce075ee458aa9065e8a4",
    "05f61704cf8fc3d050ddc36ab10536416c860e723373b3131aab123f3054c1d1",
    "d0c30bed1997960a22d56d63ffef5b6a075364422d2781b8530c8cde24b4b84e",
    "dfdd8d498fd9040450dbc944c8241da471db02adf95314c2952887a1a641ca53",
    "cba1fb1b8c534deb4e52efb11e163d05396be0e47b386a1f38eced1d8825a3d8",
})

_WORD = re.compile(r"[a-z0-9]+")
_PAIR = re.compile(r"(?=([a-z0-9]+[.\-][a-z0-9]+))")
_ADDRESS = re.compile(r"[a-z0-9._%+-]+@(?:[a-z0-9-]+\.)+[a-z]{2,}")


def _digest(word):
    return hashlib.sha256(word.encode("utf-8")).hexdigest()


def _tracked_files():
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True,
        ).stdout.decode("utf-8").split("\0")
        return [ROOT / name for name in listed if name]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", "__pycache__", "node_modules", ".pytest_cache"}
        return [p for p in ROOT.rglob("*")
                if p.is_file() and not skip.intersection(p.relative_to(ROOT).parts)]


def _words(text):
    return set(_WORD.findall(text)) | set(_PAIR.findall(text)) | set(_ADDRESS.findall(text))


def _leaks(path, base=ROOT, forbidden=FORBIDDEN):
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data[:8192]:
        return []                      # binary
    text = data.decode("utf-8", errors="replace").lower()
    if not any(_digest(word) in forbidden for word in _words(text)):
        return []
    return [
        "%s:%d" % (path.relative_to(base).as_posix(), number)
        for number, line in enumerate(text.splitlines(), 1)
        if any(_digest(word) in forbidden for word in _words(line))
    ]


def test_no_tracked_file_names_the_founder_or_a_client():
    leaks = [hit for path in _tracked_files() for hit in _leaks(path)]
    # Only locations are reported, never the words themselves.
    assert leaks == [], "private names in the public tree at: %s" % ", ".join(leaks[:50])


def test_the_court_sees_a_planted_name(tmp_path):
    """The court is not blind: a planted word, dotted handle and address are
    found in any case; the same word inside a hash is not."""
    forbidden = FORBIDDEN | {_digest("sentinel7"), _digest("first.last"),
                             _digest("someone@mail.example")}
    planted = tmp_path / "planted.txt"
    planted.write_text(
        "focus: SENTINEL7\nowner: First.Last\nmail Someone@Mail.Example\n"
        "sha256: 00sentinel7ff\n", encoding="utf-8")
    assert _leaks(planted, tmp_path, forbidden) == [
        "planted.txt:1", "planted.txt:2", "planted.txt:3"]


# A Windows profile path names the person who owns the machine. A tracked
# file may say C:\Users\<placeholder> (someone, founder, user ...) or a
# generic %LOCALAPPDATA% / %USERPROFILE% / $env: reference, never a real
# account name. Forms caught: C:\Users\<name>, the escaped double-backslash
# form, C:/Users/<name> and the Git Bash form /c/Users/<name>.
_PROFILE = re.compile(
    r"(?i)(?:\b[a-z]:(?:\\{1,2}|/)|(?<![\w.])/[a-z]/)users(?:\\{1,2}|/)([^\\/\s\"'<>`|;,)]+)"
)
PLACEHOLDER_ACCOUNTS = frozenset({
    "someone", "founder", "user", "username", "example", "public", "default",
})


def _profile_paths(path, base=ROOT):
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\0" in data[:8192]:
        return []
    text = data.decode("utf-8", errors="replace")
    return [
        "%s:%d" % (path.relative_to(base).as_posix(), number)
        for number, line in enumerate(text.splitlines(), 1)
        for match in _PROFILE.finditer(line)
        if match.group(1).lower() not in PLACEHOLDER_ACCOUNTS
        and match.group(1)[:1] not in "%$<{"
    ]


def test_no_tracked_file_holds_a_real_profile_path():
    found = [hit for path in _tracked_files() for hit in _profile_paths(path)]
    assert found == [], "machine profile paths in the public tree at: %s" % ", ".join(found[:50])


def test_the_profile_rule_sees_every_form(tmp_path):
    sep, name = "\\", "jdoe"
    planted = tmp_path / "planted.txt"
    planted.write_text("\n".join((
        "a C:" + sep + "Users" + sep + name + sep + "x.txt",
        '"d:' + sep * 2 + "users" + sep * 2 + name + sep * 2 + 'y"',
        "C:/Users/" + name + "/z",
        "cd /c/Users/" + name + "/repo",
        "C:" + sep + "Users" + sep + "someone" + sep + "fixture.md",
        "%LOCALAPPDATA%" + sep + "ArchHub",
        "C:" + sep + "Users" + sep + "%USERNAME%" + sep + "AppData",
        "https://host.example/c/users/" + name,
    )) + "\n", encoding="utf-8")
    assert _profile_paths(planted, tmp_path) == [
        "planted.txt:1", "planted.txt:2", "planted.txt:3", "planted.txt:4"]
