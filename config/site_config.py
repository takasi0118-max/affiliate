"""Site-specific configuration loading."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import PROJECT_ROOT
from utils.file_io import load_json_file, read_text_lines


@dataclass(frozen=True)
class SiteConfig:
    """Configuration files for a single affiliate site."""

    site_key: str
    site_dir: Path
    output_dir: Path
    themes: list[str]
    categories: dict[str, Any]
    tags: dict[str, Any]
    history: list[dict[str, Any]]

def load_site_config(site_key: str, output_dir: Path) -> SiteConfig:
    """Load site-specific configuration for the given site key."""
    site_dir = PROJECT_ROOT / "sites" / site_key
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    categories = load_json_file(site_dir / "categories.json")
    tags = load_json_file(site_dir / "tags.json")
    history = load_json_file(site_dir / "history.json")
    themes = read_text_lines(site_dir / "themes.txt", ignore_comments=True)

    if not isinstance(categories, dict):
        raise TypeError("categories.json must contain a JSON object.")
    if not isinstance(tags, dict):
        raise TypeError("tags.json must contain a JSON object.")
    if not isinstance(history, list):
        raise TypeError("history.json must contain a JSON array.")

    return SiteConfig(
        site_key=site_key,
        site_dir=site_dir,
        output_dir=output_dir,
        themes=themes,
        categories=categories,
        tags=tags,
        history=history,
    )
