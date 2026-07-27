"""Theme slug resolution and output path helpers."""

from __future__ import annotations

from pathlib import Path
import re

from config.settings import PROJECT_ROOT
from utils.file_io import load_json_file


ARTICLE_FILE_PREFIX = {
    "problem": "guide",
    "product": "products",
    "ranking": "ranking",
}


def load_theme_slugs(site_dir: Path) -> dict[str, str]:
    """Load Japanese theme name to English slug mapping."""
    path = site_dir / "theme_slugs.json"
    if not path.exists():
        return {}
    payload = load_json_file(path)
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object.")
    return {
        str(theme): _safe_slug(str(slug))
        for theme, slug in payload.items()
        if str(theme).strip() and str(slug).strip()
    }


def resolve_theme_slug(theme: str, site_dir: Path) -> str:
    """Return the English theme slug used for folders and filenames."""
    slugs = load_theme_slugs(site_dir)
    theme_slug = slugs.get(theme.strip())
    if not theme_slug:
        raise ValueError(
            f"Theme slug not found for '{theme}'. "
            f"Add it to {site_dir / 'theme_slugs.json'}."
        )
    return theme_slug


def article_file_prefix(article_type: str) -> str:
    """Return guide/products/ranking prefix for one article type."""
    try:
        return ARTICLE_FILE_PREFIX[article_type]
    except KeyError as error:
        raise ValueError(f"Unsupported article type: {article_type}") from error


def article_slug(article_type: str, theme_slug: str) -> str:
    """Return the Markdown/WordPress slug (= filename stem)."""
    return f"{article_file_prefix(article_type)}-{theme_slug}"


def theme_article_dir(output_dir: Path, theme_slug: str) -> Path:
    """Return output/{theme-slug}/."""
    return output_dir / theme_slug


def article_markdown_path(
    output_dir: Path,
    theme_slug: str,
    article_type: str,
) -> Path:
    """Return the Markdown path for one article type."""
    stem = article_slug(article_type, theme_slug)
    return theme_article_dir(output_dir, theme_slug) / f"{stem}.md"


def product_set_json_path(output_dir: Path, theme_slug: str) -> Path:
    """Return output/{theme-slug}/product-set-{theme-slug}.json."""
    return theme_article_dir(output_dir, theme_slug) / f"product-set-{theme_slug}.json"


def theme_product_set_path(output_dir: Path, theme: str) -> Path:
    """Resolve product-set JSON path from a Japanese theme name."""
    site_dir = output_dir.parent
    theme_slug = resolve_theme_slug(theme, site_dir)
    return product_set_json_path(output_dir, theme_slug)


def to_project_relative_path(path: Path) -> str:
    """Return a stable project-relative POSIX path string."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_slug(value: str) -> str:
    """Return a filesystem-safe ASCII slug."""
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "theme"
