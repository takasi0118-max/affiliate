"""Site-specific configuration loading."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from config.settings import PROJECT_ROOT


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


def _load_json(path: Path) -> Any:
    """Load a JSON file with a clear file path in any error."""
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Site config file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in site config file: {path}") from error


def _load_themes(path: Path) -> list[str]:
    """Load non-empty, non-comment theme lines."""
    if not path.exists():
        raise FileNotFoundError(f"Theme file not found: {path}")

    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def load_site_config(site_key: str, output_dir: Path) -> SiteConfig:
    """Load site-specific configuration for the given site key."""
    site_dir = PROJECT_ROOT / "sites" / site_key
    if not site_dir.exists():
        raise FileNotFoundError(f"Site directory not found: {site_dir}")

    categories = _load_json(site_dir / "categories.json")
    tags = _load_json(site_dir / "tags.json")
    history = _load_json(site_dir / "history.json")
    themes = _load_themes(site_dir / "themes.txt")

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
