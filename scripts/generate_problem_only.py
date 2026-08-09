"""Generate standalone problem-only articles (separate from the 3-article set).

Usage:
    python scripts/generate_problem_only.py
    python scripts/generate_problem_only.py --list
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from config.site_config import load_site_config
from google.genai import errors
from providers.gemini_provider import GeminiApiError, GeminiProvider
from providers.wordpress_provider import WordPressApiError, WordPressProvider
from services.article_generator import ArticleGenerator
from services.markdown_service import MarkdownService
from services.problem_only_link_service import (
    apply_related_article_links,
    select_related_article_links,
)
from services.prompt_manager import PromptManager
from services.seo_service import (
    SeoService,
    replace_seo_slug,
    strip_year_from_problem_seo_title,
)
from services.site_manager import HistoryEntry
from services.theme_path_service import (
    article_slug,
    resolve_problem_theme_slug,
    to_project_relative_path,
)
from services.wordpress_post_service import WordPressPostService
from utils.file_io import load_json_file, read_text_lines, save_json_file
from utils.logger import setup_logging


logger = logging.getLogger(__name__)


def _load_problem_themes(site_dir: Path) -> list[str]:
    return read_text_lines(site_dir / "problem_themes.txt", ignore_comments=True)


def _load_problem_history(site_dir: Path) -> list[dict]:
    path = site_dir / "problem_history.json"
    if not path.exists():
        return []
    payload = load_json_file(path)
    if not isinstance(payload, list):
        raise TypeError(f"{path} must contain a JSON array.")
    return payload


def _processed_problem_themes(history: list[dict]) -> set[str]:
    return {
        str(record["theme"])
        for record in history
        if isinstance(record, dict) and record.get("theme")
    }


def _next_problem_theme(site_dir: Path) -> str | None:
    history = _load_problem_history(site_dir)
    processed = _processed_problem_themes(history)
    available = [
        theme
        for theme in _load_problem_themes(site_dir)
        if theme not in processed
    ]
    return available[0] if available else None


def _record_problem_history(
    site_dir: Path,
    *,
    theme: str,
    title: str,
    slug: str,
    markdown_path: str,
    wordpress_post_id: int | None,
) -> None:
    history = _load_problem_history(site_dir)
    status = "draft" if wordpress_post_id and wordpress_post_id > 0 else "generated"
    history.append(
        HistoryEntry(
            theme=theme,
            article_type="problem_only",
            title=title,
            slug=slug,
            markdown_path=markdown_path,
            status=status,
            wordpress_post_id=wordpress_post_id if wordpress_post_id and wordpress_post_id > 0 else None,
            created_at=datetime.now(UTC).isoformat(),
        ).to_dict()
    )
    save_json_file(site_dir / "problem_history.json", history)


def _list_themes(site_dir: Path) -> None:
    history = _load_problem_history(site_dir)
    processed = _processed_problem_themes(history)
    themes = _load_problem_themes(site_dir)
    print(f"Problem-only themes: {len(themes)}")
    print(f"Processed: {len(processed)}")
    for theme in themes:
        mark = "done" if theme in processed else "todo"
        print(f"  [{mark}] {theme}")
    next_theme = _next_problem_theme(site_dir)
    print(f"Next: {next_theme or '(none)'}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate one standalone problem-only article."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List problem-only themes and exit.",
    )
    args = parser.parse_args()

    settings = load_settings()
    setup_logging(
        log_level=settings.log_level,
        log_file=PROJECT_ROOT / "logs" / "app.log",
    )
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    site_dir = site_config.site_dir

    if args.list:
        _list_themes(site_dir)
        return

    next_theme = _next_problem_theme(site_dir)
    if next_theme is None:
        print("No available problem-only themes.")
        print("Add themes to sites/disaster/problem_themes.txt")
        print("and matching slugs to sites/disaster/problem_theme_slugs.json")
        return

    theme_slug = resolve_problem_theme_slug(next_theme, site_dir)
    # 悩み記事のみも通常の悩み記事と同じく guide- プレフィックスで固定する。
    forced_slug = article_slug("problem_only", theme_slug)
    if not forced_slug.startswith("guide-"):
        raise ValueError(f"Problem-only slug must start with guide-: {forced_slug}")

    prompt_manager = PromptManager(site_config.site_key)
    gemini = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    article_generator = ArticleGenerator(prompt_manager, gemini)
    seo_service = SeoService()
    markdown_service = MarkdownService()
    wordpress_provider = WordPressProvider(
        site_url=settings.wordpress_url,
        username=settings.wordpress_username,
        app_password=settings.wordpress_app_password,
    )
    wordpress_post_service = WordPressPostService(wordpress_provider)

    wordpress_connected = False
    wordpress_error = ""
    try:
        wordpress_provider.test_connection()
        wordpress_connected = True
    except (WordPressApiError, requests.RequestException) as error:
        wordpress_error = str(error)
        logger.error("WordPress connection failed: %s", error)

    category = site_config.categories.get("default", "防災")
    if not isinstance(category, str):
        category = "防災"
    tags = site_config.tags.get("default", [])
    if not isinstance(tags, list):
        tags = []

    print(f"Theme: {next_theme}")
    print(f"Slug: {forced_slug}")

    try:
        article = article_generator.generate_problem_only_article(
            theme=next_theme,
            category=category,
            tags=[str(tag) for tag in tags if isinstance(tag, str)],
        )
    except (GeminiApiError, errors.APIError, requests.RequestException) as error:
        logger.error("Problem-only generation failed: %s", error)
        print(f"Gemini failed: {error}")
        return

    seo = replace_seo_slug(
        strip_year_from_problem_seo_title(seo_service.analyze_article(article.content)),
        forced_slug,
    )
    related_links = select_related_article_links(
        site_config.history,
        next_theme,
        site_dir,
        target_count=8,
    )
    article = apply_related_article_links(
        article,
        related_links,
        footer_count=3,
        inline_count=5,
    )

    saved = markdown_service.save_article(
        article,
        seo,
        site_config.output_dir,
        theme_slug=theme_slug,
    )
    relative_path = to_project_relative_path(saved.path)

    wordpress_post_id: int | None = None
    if wordpress_connected:
        try:
            posted = wordpress_post_service.create_draft_post(article, seo)
            wordpress_post_id = posted.post_id
        except (WordPressApiError, requests.RequestException, ValueError) as error:
            wordpress_error = str(error)
            logger.error("WordPress draft create failed: %s", error)

    _record_problem_history(
        site_dir,
        theme=next_theme,
        title=seo.seo_title or next_theme,
        slug=forced_slug,
        markdown_path=relative_path,
        wordpress_post_id=wordpress_post_id,
    )

    print(f"Markdown saved: {relative_path}")
    print(f"Related links: {len(related_links)}")
    for link in related_links:
        print(f"  - {link.title} ({link.url})")
    print(f"Characters: {article.character_count}")
    print(f"SEO ready: {seo.is_ready}")
    print(f"WordPress connected: {wordpress_connected}")
    if wordpress_post_id:
        print(f"WordPress draft id: {wordpress_post_id}")
    elif wordpress_error:
        print(f"WordPress error: {wordpress_error}")
    print("Recorded in problem_history.json")


if __name__ == "__main__":
    main()
