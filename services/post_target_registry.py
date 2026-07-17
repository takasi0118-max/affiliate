"""Load WordPress post update targets from site history."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT, load_settings
from config.site_config import load_site_config


@dataclass(frozen=True)
class PostTarget:
    """One WordPress post and its source Markdown file."""

    post_id: int
    article_type: str
    markdown_path: Path
    theme: str = ""
    needs_products: bool = False
    product_markdown_path: Path | None = None


LEGACY_POST_TARGETS: dict[int, PostTarget] = {
    8: PostTarget(
        8,
        "problem",
        Path("sites/disaster/output/problem-emergency-backpack-how-to-choose.md"),
        theme="防災リュック",
        needs_products=True,
        product_markdown_path=Path(
            "sites/disaster/output/product-bousai-rucksack-select.md"
        ),
    ),
    9: PostTarget(
        9,
        "product",
        Path("sites/disaster/output/product-bousai-rucksack-select.md"),
        theme="防災リュック",
    ),
    10: PostTarget(
        10,
        "ranking",
        Path("sites/disaster/output/ranking-bousai-backpack-ranking.md"),
        theme="防災リュック",
    ),
}


def load_theme_slugs(history: list[dict]) -> dict[str, set[str]]:
    """Return allowed article slugs grouped by theme."""
    slugs_by_theme: dict[str, set[str]] = {}
    for record in history:
        if not isinstance(record, dict):
            continue
        theme = str(record.get("theme", ""))
        slug = str(record.get("slug", "")).strip().strip("/")
        if theme and slug:
            slugs_by_theme.setdefault(theme, set()).add(slug)
    return slugs_by_theme


def load_post_targets() -> dict[int, PostTarget]:
    """Return post targets merged from history.json and legacy defaults."""
    settings = load_settings()
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    targets = dict(LEGACY_POST_TARGETS)
    targets.update(_build_targets_from_history(site_config.history))
    return targets


def load_allowed_slugs_by_theme() -> dict[str, set[str]]:
    """Return allowed article slugs grouped by theme from site history."""
    settings = load_settings()
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    slugs_by_theme = load_theme_slugs(site_config.history)
    if not slugs_by_theme:
        slugs_by_theme = {
            "防災リュック": {
                "emergency-backpack-how-to-choose",
                "bousai-rucksack-select",
                "bousai-backpack-ranking",
            },
        }
    return slugs_by_theme


def _build_targets_from_history(history: list[dict[str, Any]]) -> dict[int, PostTarget]:
    """Build post targets from history.json records."""
    product_paths_by_theme = {
        str(record["theme"]): _normalize_markdown_path(str(record["markdown_path"]))
        for record in history
        if _is_history_record(record)
        and record.get("article_type") == "product"
        and record.get("theme")
        and record.get("markdown_path")
    }

    targets: dict[int, PostTarget] = {}
    for record in history:
        if not _is_history_record(record):
            continue

        post_id = record.get("wordpress_post_id")
        article_type = str(record.get("article_type", ""))
        markdown_path = record.get("markdown_path")
        if not isinstance(post_id, int) or post_id <= 0:
            continue
        if article_type not in {"problem", "product", "ranking"}:
            continue
        if not isinstance(markdown_path, str) or not markdown_path:
            continue

        theme = str(record.get("theme", ""))
        needs_products = article_type == "problem"
        targets[post_id] = PostTarget(
            post_id=post_id,
            article_type=article_type,
            markdown_path=_normalize_markdown_path(markdown_path),
            theme=theme,
            needs_products=needs_products,
            product_markdown_path=(
                product_paths_by_theme.get(theme) if needs_products else None
            ),
        )
    return targets


def _is_history_record(record: Any) -> bool:
    """Return whether one history.json item is a mapping."""
    return isinstance(record, dict)


def _normalize_markdown_path(path_str: str) -> Path:
    """Return a project-relative Markdown path when possible."""
    path = Path(path_str)
    if path.is_absolute():
        try:
            return path.relative_to(PROJECT_ROOT)
        except ValueError:
            return path
    return path
