"""Load WordPress post update targets from site history."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT, load_settings
from config.site_config import load_site_config
from utils.file_io import load_json_file


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
        Path("sites/disaster/output/emergency-backpack/guide-emergency-backpack.md"),
        theme="防災リュック",
    ),
    9: PostTarget(
        9,
        "product",
        Path("sites/disaster/output/emergency-backpack/products-emergency-backpack.md"),
        theme="防災リュック",
        needs_products=False,
        product_markdown_path=Path(
            "sites/disaster/output/emergency-backpack/products-emergency-backpack.md"
        ),
    ),
    10: PostTarget(
        10,
        "ranking",
        Path("sites/disaster/output/emergency-backpack/ranking-emergency-backpack.md"),
        theme="防災リュック",
    ),
}

_SUPPORTED_ARTICLE_TYPES = {"problem", "problem_only", "product", "ranking"}


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
    """Return post targets merged from history files and legacy defaults."""
    settings = load_settings()
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    targets = dict(LEGACY_POST_TARGETS)
    targets.update(_build_targets_from_history(site_config.history))
    targets.update(_build_targets_from_history(_load_problem_history(site_config.site_dir)))
    return targets


def load_allowed_slugs_by_theme() -> dict[str, set[str]]:
    """Return allowed article slugs grouped by theme from site history."""
    settings = load_settings()
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    main_history = site_config.history
    problem_history = _load_problem_history(site_config.site_dir)
    slugs_by_theme = load_theme_slugs(main_history)
    for theme, slugs in load_theme_slugs(problem_history).items():
        slugs_by_theme.setdefault(theme, set()).update(slugs)

    # Problem-only articles link across product themes, so allow those slugs too.
    all_product_slugs = {
        slug
        for slugs in load_theme_slugs(main_history).values()
        for slug in slugs
    }
    problem_only_themes = {
        str(record.get("theme"))
        for record in problem_history
        if record.get("article_type") == "problem_only" and record.get("theme")
    }
    for theme in problem_only_themes:
        slugs_by_theme[theme] = set(slugs_by_theme.get(theme, set())) | all_product_slugs

    if not slugs_by_theme:
        slugs_by_theme = {
            "防災リュック": {
                "guide-emergency-backpack",
                "products-emergency-backpack",
                "ranking-emergency-backpack",
            },
        }
    return slugs_by_theme


def _load_problem_history(site_dir: Path) -> list[dict[str, Any]]:
    """Load problem-only history records when the file exists."""
    path = site_dir / "problem_history.json"
    if not path.exists():
        return []
    payload = load_json_file(path)
    if not isinstance(payload, list):
        raise TypeError(f"{path} must contain a JSON array.")
    return [record for record in payload if isinstance(record, dict)]


def _build_targets_from_history(history: list[dict[str, Any]]) -> dict[int, PostTarget]:
    """Build post targets from history records."""
    targets: dict[int, PostTarget] = {}
    for record in history:
        if not _is_history_record(record):
            continue

        post_id = record.get("wordpress_post_id")
        article_type = str(record.get("article_type", ""))
        markdown_path = record.get("markdown_path")
        if not isinstance(post_id, int) or post_id <= 0:
            continue
        if article_type not in _SUPPORTED_ARTICLE_TYPES:
            continue
        if not isinstance(markdown_path, str) or not markdown_path:
            continue

        theme = str(record.get("theme", ""))
        targets[post_id] = PostTarget(
            post_id=post_id,
            article_type=article_type,
            markdown_path=_normalize_markdown_path(markdown_path),
            theme=theme,
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
