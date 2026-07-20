"""Normalize product detail headings in one saved Markdown file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.markdown_product_block_service import normalize_product_detail_sections


def split_front_matter(content: str) -> tuple[str, str]:
    """Return front matter and body from one Markdown file."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", content

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            front_matter = "\n".join(lines[: index + 1]) + "\n"
            body = "\n".join(lines[index + 1 :]).strip() + "\n"
            return front_matter, body

    return "", content


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown_path", type=Path)
    args = parser.parse_args()

    path = args.markdown_path
    front_matter, body = split_front_matter(path.read_text(encoding="utf-8"))
    normalized = normalize_product_detail_sections(body)
    path.write_text(front_matter + normalized, encoding="utf-8")
    print(f"Updated: {path}")
    print(f"#### 特徴: {normalized.count('#### 特徴')}")
    print(f"inline bullets: {normalized.count('* **特徴**:')}")


if __name__ == "__main__":
    main()
