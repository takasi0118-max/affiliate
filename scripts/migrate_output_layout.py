"""Migrate flat output files into theme folders with guide/best/ranking names."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.theme_path_service import (
    article_markdown_path,
    article_slug,
    product_set_json_path,
    resolve_theme_slug,
    to_project_relative_path,
)


SITE_DIR = PROJECT_ROOT / "sites" / "disaster"
OUTPUT_DIR = SITE_DIR / "output"
HISTORY_PATH = SITE_DIR / "history.json"

MIGRATIONS = {
    "防災リュック": {
        "problem": [
            OUTPUT_DIR / "problem-emergency-backpack-how-to-choose.md",
            OUTPUT_DIR / "emergency-backpack" / "guide-emergency-backpack.md",
        ],
        "product": [
            OUTPUT_DIR / "product-bousai-rucksack-select.md",
            OUTPUT_DIR / "emergency-backpack" / "best-emergency-backpack.md",
        ],
        "ranking": [
            OUTPUT_DIR / "ranking-bousai-backpack-ranking.md",
            OUTPUT_DIR / "emergency-backpack" / "ranking-emergency-backpack.md",
        ],
        "catalog": [
            OUTPUT_DIR / "product-set-防災リュック.json",
            OUTPUT_DIR / "emergency-backpack" / "product-set-emergency-backpack.json",
        ],
    },
    "非常食": {
        "problem": [OUTPUT_DIR / "problem-emergency-food-how-many-days.md"],
        "product": [OUTPUT_DIR / "product-emergency-food-sets.md"],
        "ranking": [OUTPUT_DIR / "ranking-emergency-food-ranking.md"],
        "catalog": [OUTPUT_DIR / "product-set-非常食.json"],
    },
    "ポータブル電源": {
        "problem": [
            OUTPUT_DIR / "problem-portable-power-station-disaster-prevention.md"
        ],
        "product": [
            OUTPUT_DIR / "product-portable-power-station-disaster-prevention.md"
        ],
        "ranking": [
            OUTPUT_DIR / "ranking-portable-power-station-disaster-prevention.md"
        ],
        "catalog": [OUTPUT_DIR / "product-set-ポータブル電源.json"],
    },
}


def _rewrite_slug(path: Path, slug: str) -> None:
    """Force front-matter slug to match the filename stem."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return
    updated: list[str] = [lines[0]]
    closed = False
    for line in lines[1:]:
        if not closed and line.strip() == "---":
            updated.append(line)
            closed = True
            continue
        if not closed and line.startswith("slug:"):
            updated.append(f"slug: {slug}")
            continue
        updated.append(line)
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def migrate_theme(theme: str, mapping: dict[str, list[Path]]) -> None:
    """Move one theme's files into the new folder layout."""
    theme_slug = resolve_theme_slug(theme, SITE_DIR)
    for article_type in ("problem", "product", "ranking"):
        source = _first_existing(mapping[article_type])
        target = article_markdown_path(OUTPUT_DIR, theme_slug, article_type)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is None:
            print(f"Skip missing {article_type}: {theme}")
            continue
        if source.resolve() != target.resolve():
            shutil.move(str(source), str(target))
            print(f"Moved {source.name} -> {target.relative_to(PROJECT_ROOT)}")
        _rewrite_slug(target, article_slug(article_type, theme_slug))

    catalog_source = _first_existing(mapping["catalog"])
    catalog_target = product_set_json_path(OUTPUT_DIR, theme_slug)
    catalog_target.parent.mkdir(parents=True, exist_ok=True)
    if catalog_source is None:
        print(f"Skip missing catalog: {theme}")
        return
    if catalog_source.resolve() != catalog_target.resolve():
        shutil.move(str(catalog_source), str(catalog_target))
        print(
            f"Moved {catalog_source.name} -> "
            f"{catalog_target.relative_to(PROJECT_ROOT)}"
        )


def update_history() -> None:
    """Rewrite history.json paths and slugs to the new layout."""
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    for record in history:
        if not isinstance(record, dict):
            continue
        theme = str(record.get("theme", ""))
        article_type = str(record.get("article_type", ""))
        if not theme or article_type not in {"problem", "product", "ranking"}:
            continue
        theme_slug = resolve_theme_slug(theme, SITE_DIR)
        path = article_markdown_path(OUTPUT_DIR, theme_slug, article_type)
        record["slug"] = article_slug(article_type, theme_slug)
        record["markdown_path"] = to_project_relative_path(path)
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {HISTORY_PATH.relative_to(PROJECT_ROOT)}")


def main() -> None:
    for theme, mapping in MIGRATIONS.items():
        migrate_theme(theme, mapping)
    update_history()


if __name__ == "__main__":
    main()
