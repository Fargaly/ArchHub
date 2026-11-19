"""The public surfaces shared by packaging, the website and the README."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


SOURCE = Path(__file__).with_name("links.json")


def load_links():
    rows = json.loads(SOURCE.read_text(encoding="utf-8"))
    kinds = [row["kind"] for row in rows]
    if len(kinds) != len(set(kinds)):
        raise ValueError("Public link kinds must be unique")
    for row in rows:
        url = urlsplit(row["url"])
        if not row["name"] or url.scheme != "https" or not url.netloc or url.username or url.password:
            raise ValueError("Public links need a name and an HTTPS address without credentials")
    return rows


def readme_table():
    return "\n".join(
        f'- **{row["name"]}**: [{row["url"]}]({row["url"]})' for row in load_links()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, help="Refresh the marked generated Links table")
    args = parser.parse_args()
    table = readme_table()
    if args.readme:
        text = args.readme.read_text(encoding="utf-8")
        pattern = r"(<!-- PUBLIC LINKS:BEGIN -->)\n.*?(<!-- PUBLIC LINKS:END -->)"
        updated, count = re.subn(pattern, lambda m: m[1] + "\n" + table + "\n" + m[2], text, flags=re.S)
        if count != 1:
            raise ValueError("README must contain exactly one PUBLIC LINKS marker pair")
        args.readme.write_text(updated, encoding="utf-8")
    else:
        print(table)


if __name__ == "__main__":
    main()
