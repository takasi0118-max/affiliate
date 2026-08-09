"""Update existing WordPress posts from saved Markdown files.

Usage:
    python scripts/update_wordpress_posts.py
    python scripts/update_wordpress_posts.py 9
    python scripts/update_wordpress_posts.py 8 10
    python scripts/update_wordpress_posts.py --list

Post targets are loaded from sites/{SITE_KEY}/history.json.
Legacy post IDs 8, 9, and 10 remain available until history.json contains them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from providers.rakuten_provider import RakutenProduct, RakutenProvider
from providers.wordpress_provider import WordPressProvider
from services.article_product_block_builder import (
    MIN_PRODUCT_BLOCKS_BY_TYPE,
    ensure_affiliate_blocks_for_theme_markdown,
)
from services.post_target_registry import (
    PostTarget,
    load_allowed_slugs_by_theme,
    load_post_targets,
)
from services.article_link_sanitizer import sanitize_article_references
from services.markdown_product_block_service import (
    has_product_blocks,
    normalize_product_detail_sections,
    parse_products_from_markdown,
)
from services.inline_related_link_service import (
    InlineRelatedLinkService,
    load_theme_article_links,
)
from services.seo_service import SeoService, strip_year_from_problem_seo_title
from services.calendar_year_normalizer import strip_calendar_year_from_seo_title_fields
from services.wordpress_post_service import WordPressPostService


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Update existing WordPress posts from saved Markdown files.",
    )
    parser.add_argument(
        "post_ids",
        nargs="*",
        type=int,
        help="WordPress post IDs to update. Omit to update all registered posts.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Show registered post IDs and exit.",
    )
    return parser


def resolve_targets(
    post_ids: Sequence[int],
    post_targets: dict[int, PostTarget],
) -> list[PostTarget]:
    """Return the post targets selected on the command line."""
    if not post_ids:
        return [post_targets[post_id] for post_id in sorted(post_targets)]

    unknown_ids = [post_id for post_id in post_ids if post_id not in post_targets]
    if unknown_ids:
        known = ", ".join(str(post_id) for post_id in sorted(post_targets))
        unknown = ", ".join(str(post_id) for post_id in unknown_ids)
        raise SystemExit(f"Unknown post ID(s): {unknown}. Registered IDs: {known}")

    return [post_targets[post_id] for post_id in post_ids]


def print_registered_posts(post_targets: dict[int, PostTarget]) -> None:
    """Print the registered post mapping."""
    for post_id in sorted(post_targets):
        target = post_targets[post_id]
        theme_label = f" [{target.theme}]" if target.theme else ""
        print(
            f"{post_id}: {target.article_type}{theme_label} -> "
            f"{target.markdown_path.as_posix()}"
        )


def _resolve_product_source(target: PostTarget) -> Path | None:
    """Return the product Markdown used to build problem-article product cards."""
    if target.product_markdown_path is not None:
        return PROJECT_ROOT / target.product_markdown_path
    return None


def _validate_product_blocks(target: PostTarget, markdown_content: str) -> None:
    """Abort when product or ranking articles would lose affiliate blocks."""
    minimum = MIN_PRODUCT_BLOCKS_BY_TYPE.get(target.article_type)
    if minimum is None:
        return
    if has_product_blocks(markdown_content, minimum=minimum):
        return
    raise SystemExit(
        f"Post {target.post_id} ({target.article_type}) has no Rakuten product "
        f"image links in {target.markdown_path.as_posix()}. "
        "Restore affiliate blocks before updating."
    )


def _validate_problem_products(target: PostTarget, products: list[RakutenProduct]) -> None:
    """Abort when a problem article cannot rebuild product mini cards."""
    if not target.needs_products:
        return
    if products:
        return
    product_source = _resolve_product_source(target)
    source_label = (
        product_source.relative_to(PROJECT_ROOT).as_posix()
        if product_source is not None
        else "product markdown"
    )
    raise SystemExit(
        f"Post {target.post_id} (problem) needs product data from {source_label}, "
        "but no Rakuten product blocks were found. Restore affiliate blocks first."
    )


def update_posts(targets: Sequence[PostTarget]) -> None:
    """Update the selected WordPress posts."""
    settings = load_settings()
    provider = WordPressProvider(
        site_url=settings.wordpress_url,
        username=settings.wordpress_username,
        app_password=settings.wordpress_app_password,
    )
    rakuten_provider = RakutenProvider(
        application_id=settings.rakuten_application_id,
        access_key=settings.rakuten_access_key,
        affiliate_id=settings.rakuten_affiliate_id,
    )
    service = WordPressPostService(provider)
    seo_service = SeoService()
    product_cache: dict[Path, list[RakutenProduct]] = {}
    allowed_slugs_by_theme = load_allowed_slugs_by_theme()
    theme_article_links = load_theme_article_links()
    inline_link_service = InlineRelatedLinkService()

    provider.test_connection()
    print("WordPress connection: OK")

    for target in targets:
        markdown_path = PROJECT_ROOT / target.markdown_path
        if not markdown_path.exists():
            raise SystemExit(f"Markdown file not found: {markdown_path}")

        article_products: list[RakutenProduct] | None = None
        if target.needs_products:
            product_source = _resolve_product_source(target)
            if product_source is None:
                raise SystemExit(
                    f"Product markdown not found for problem post {target.post_id}."
                )
            if not product_source.exists():
                raise SystemExit(f"Product markdown file not found: {product_source}")
            if product_source not in product_cache:
                product_cache[product_source] = parse_products_from_markdown(
                    product_source.read_text(encoding="utf-8")
                )
                print(
                    f"Parsed {len(product_cache[product_source])} products from "
                    f"{product_source.relative_to(PROJECT_ROOT).as_posix()}"
                )
            article_products = product_cache[product_source]
            _validate_problem_products(target, article_products)

        markdown_content = markdown_path.read_text(encoding="utf-8")
        if target.article_type in MIN_PRODUCT_BLOCKS_BY_TYPE and target.theme:
            repaired_content, _ = ensure_affiliate_blocks_for_theme_markdown(
                markdown_content,
                target.theme,
                target.article_type,
                output_dir=settings.output_dir,
                rakuten_provider=rakuten_provider,
            )
            if repaired_content != markdown_content:
                markdown_path.write_text(repaired_content, encoding="utf-8")
                print(
                    f"Repaired Rakuten affiliate blocks in "
                    f"{markdown_path.relative_to(PROJECT_ROOT).as_posix()}"
                )
                markdown_content = repaired_content
        if target.article_type == "product":
            normalized_content = normalize_product_detail_sections(markdown_content)
            if normalized_content != markdown_content:
                markdown_path.write_text(normalized_content, encoding="utf-8")
                print(
                    f"Normalized product detail headings in "
                    f"{markdown_path.relative_to(PROJECT_ROOT).as_posix()}"
                )
                markdown_content = normalized_content
        allowed_slugs = allowed_slugs_by_theme.get(target.theme, set())
        if allowed_slugs:
            markdown_content = sanitize_article_references(
                markdown_content,
                allowed_slugs,
            )
        if target.theme:
            markdown_content = inline_link_service.apply(
                markdown_content,
                target.article_type,
                target.theme,
                theme_article_links,
            )
        _validate_product_blocks(target, markdown_content)
        if target.article_type in {"problem", "problem_only"}:
            stripped = strip_calendar_year_from_seo_title_fields(markdown_content)
            if stripped != markdown_content:
                markdown_path.write_text(stripped, encoding="utf-8")
                markdown_content = stripped
            seo = strip_year_from_problem_seo_title(
                seo_service.analyze_article(markdown_content)
            )
        else:
            seo = seo_service.analyze_article(markdown_content)
        updated_id = service.update_post_with_markdown(
            post_id=target.post_id,
            markdown_content=markdown_content,
            seo=seo,
            article_type=target.article_type,
            products=article_products,
        )
        post = provider.get_post(updated_id)
        title = post.get("title", {}).get("rendered", "")
        print(
            f"Post {updated_id} ({target.article_type}): updated, "
            f"status={post.get('status')}, title={title}"
        )


def main(argv: Sequence[str] | None = None) -> None:
    """Run the CLI."""
    args = build_parser().parse_args(argv)
    post_targets = load_post_targets()

    if args.list:
        print_registered_posts(post_targets)
        return

    targets = resolve_targets(args.post_ids, post_targets)
    update_posts(targets)


if __name__ == "__main__":
    main()
