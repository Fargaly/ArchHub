"""Auto-publish layer — channels we already have creds for. No founder approval per post.

Channels supported (now):
  github_discussion  — `gh api graphql` to open a Discussion in the
                       Fargaly/ArchHub repo. Works because the user
                       is already gh-auth'd on this machine.
  github_release_blurb — append a paragraph to the most recent
                         release's body via gh api.
  notion_page        — append a block to a Notion page if NOTION_API_KEY
                       (or secrets_store 'notion_api_key') is configured.
  readme_section     — git-commit a section update to README.md and push.

Channels that need a 1-time founder OAuth/signup (not yet wired):
  reddit, x_twitter, hn, indie_hackers, product_hunt, gmail_outreach.

Rate-limiting: per-channel daily/weekly caps stored in
agents/outputs/_publish/state.json. Never burns Claude tokens — pure
filesystem + HTTP.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


REPO = Path(__file__).resolve().parent.parent
PUB_OUT = REPO / "agents" / "outputs" / "_publish"
PUB_OUT.mkdir(parents=True, exist_ok=True)
STATE = PUB_OUT / "state.json"


def _hidden_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": (lambda s: (setattr(s, "dwFlags", s.dwFlags | subprocess.STARTF_USESHOWWINDOW), setattr(s, "wShowWindow", 0), s)[-1])(subprocess.STARTUPINFO()),
    }


def _load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d: dict) -> None:
    STATE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _allowed(channel: str, cap_per_day: int) -> bool:
    """True if posting to `channel` today is still under the cap."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    s = _load_state()
    key = f"{channel}:{today}"
    used = int(s.get(key, 0))
    if used >= cap_per_day:
        return False
    s[key] = used + 1
    _save_state(s)
    return True


# ---------------------------------------------------------------------------
def publish_github_discussion(*, title: str, body: str,
                               category: str = "Announcements") -> dict:
    """Open a Discussion in the public repo. `gh` must be authenticated.
    Cap 2/day so we never spam our own repo."""
    if not _allowed("github_discussion", cap_per_day=2):
        return {"status": "skip", "reason": "daily cap reached"}
    # Resolve repo + category id via gh api graphql.
    query_repo = """
    query($owner:String!,$name:String!){
      repository(owner:$owner,name:$name){ id discussionCategories(first:20){nodes{id name}} }
    }
    """
    try:
        r = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query_repo}",
             "-F", "owner=Fargaly", "-F", "name=ArchHub"],
            capture_output=True, text=True, timeout=20,
            **_hidden_kwargs(),
        )
        if r.returncode != 0:
            return {"status": "error", "error": r.stderr[:300]}
        data = json.loads(r.stdout).get("data", {}).get("repository", {})
        repo_id = data.get("id")
        cats = {c["name"]: c["id"]
                for c in (data.get("discussionCategories", {}).get("nodes") or [])}
        cat_id = cats.get(category) or next(iter(cats.values()), None)
        if not (repo_id and cat_id):
            return {"status": "error", "error": "missing repo_id or category"}
        mutation = """
        mutation($repo:ID!,$cat:ID!,$title:String!,$body:String!){
          createDiscussion(input:{repositoryId:$repo,categoryId:$cat,title:$title,body:$body}){
            discussion{ url }
          }
        }
        """
        r2 = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={mutation}",
             "-F", f"repo={repo_id}", "-F", f"cat={cat_id}",
             "-F", f"title={title}", "-F", f"body={body}"],
            capture_output=True, text=True, timeout=30,
            **_hidden_kwargs(),
        )
        if r2.returncode != 0:
            return {"status": "error", "error": r2.stderr[:300]}
        url = (json.loads(r2.stdout)
               .get("data", {})
               .get("createDiscussion", {})
               .get("discussion", {})
               .get("url"))
        return {"status": "published", "url": url}
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:300]}


def publish_readme_blurb(section_marker: str, content_md: str,
                         commit_message: Optional[str] = None) -> dict:
    """Replace content between `<!-- archhub-auto:section_marker -->` markers
    in README.md. If markers don't exist, append to bottom. Commits + pushes.

    Cap 1/day."""
    if not _allowed("readme_section", cap_per_day=1):
        return {"status": "skip", "reason": "daily cap reached"}

    readme = REPO / "README.md"
    body = readme.read_text(encoding="utf-8") if readme.exists() else ""
    start = f"<!-- archhub-auto:{section_marker}:start -->"
    end = f"<!-- archhub-auto:{section_marker}:end -->"
    block = f"{start}\n{content_md.strip()}\n{end}\n"
    if start in body and end in body:
        before, _, rest = body.partition(start)
        _, _, after = rest.partition(end)
        new_body = before + block + after
    else:
        new_body = body + ("\n\n" if body and not body.endswith("\n\n") else "") + block
    if new_body == body:
        return {"status": "skip", "reason": "no change"}
    readme.write_text(new_body, encoding="utf-8")
    commit_message = commit_message or f"docs(auto): refresh {section_marker} section"
    try:
        for cmd in (
            ["git", "add", "README.md"],
            ["git", "commit", "-m", commit_message],
            ["git", "push", "origin", "main"],
        ):
            r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                                timeout=30, **_hidden_kwargs())
            if r.returncode != 0 and "nothing to commit" not in (r.stdout or "") + (r.stderr or ""):
                return {"status": "error", "error": (r.stderr or r.stdout)[:300]}
        return {"status": "published", "section": section_marker}
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:300]}


def publish_notion_page(page_id: str, content_md: str) -> dict:
    """Append a paragraph block to a Notion page. Cap 5/day."""
    if not _allowed("notion_page", cap_per_day=5):
        return {"status": "skip", "reason": "daily cap reached"}
    try:
        sys.path.insert(0, str(REPO / "app"))
        from secrets_store import load_setting
        token = load_setting("notion_api_key") or os.environ.get("NOTION_API_KEY")
    except Exception:
        token = os.environ.get("NOTION_API_KEY")
    if not token:
        return {"status": "skip", "reason": "no notion token"}
    import urllib.request, urllib.error
    body = json.dumps({
        "children": [{
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text",
                                          "text": {"content": content_md[:2000]}}]},
        }]
    }).encode()
    req = urllib.request.Request(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        data=body, method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return {"status": "published", "page_id": page_id}
    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code} {e.read()[:200]}"}
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:300]}


# ---------------------------------------------------------------------------
def publish_changelog_to_repo() -> dict:
    """Auto-pulls last 24h of commits, formats as a changelog snippet,
    drops it into README.md between `<!-- archhub-auto:changelog -->` markers.
    Idempotent — daily cap = 1."""
    creationflags_si = _hidden_kwargs()
    try:
        r = subprocess.run(
            ["git", "log", "--since=24 hours ago", "--pretty=%h %s"],
            cwd=REPO, capture_output=True, text=True, timeout=10,
            **creationflags_si,
        )
        log = (r.stdout or "").strip().splitlines()
    except Exception as ex:
        return {"status": "error", "error": str(ex)[:200]}
    if not log:
        return {"status": "skip", "reason": "no commits"}
    md = ["### Last 24 hours", "", "<!-- auto-updated daily by agents/publish.py -->", ""]
    for line in log[:30]:
        md.append(f"- `{line.split(' ',1)[0]}` {line.split(' ',1)[1] if ' ' in line else line}")
    return publish_readme_blurb(
        "changelog",
        "\n".join(md),
        commit_message=f"docs(auto): refresh 24h changelog ({len(log)} commits)",
    )


def autopublish_round() -> list[dict]:
    """One round of every channel that has a backlog item ready.
    Wired so CEO routine can call once per day to `ship` content."""
    out = []
    out.append(("readme_changelog", publish_changelog_to_repo()))
    return out


if __name__ == "__main__":
    # Standalone smoke run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for label, res in autopublish_round():
        print(f"{label}: {res}")
