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
import re
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from providers.rakuten_provider import RakutenProduct
from providers.wordpress_provider import WordPressProvider
from services.post_target_registry import PostTarget, load_post_targets
from services.seo_service import SeoService
from services.wordpress_post_service import WordPressPostService

PRODUCT_BLOCK_PATTERN = re.compile(
    r"\[!\[(?P<name>[^\]]+)\]\((?P<img>[^)]+)\)\]\((?P<url>[^)]+)\)\s*\n\s*\n"
    r"\*\s+\*\*価格\*\*:\s*(?P<price>[^\n]+)\n"
    r"\*\s+\*\*レビュー評価\*\*:\s*(?P<review>[0-9.]+)[^\n]*件数:\s*(?P<count>[0-9,]+)件",
    re.S,
)


def parse_products_from_markdown(path: Path) -> list[RakutenProduct]:
    """Read Rakuten product metadata blocks from a product article Markdown file."""
    product_md = path.read_text(encoding="utf-8")
    products: list[RakutenProduct] = []
    for match in PRODUCT_BLOCK_PATTERN.finditer(product_md):
        price_digits = re.sub(r"\D", "", match.group("price"))
        count_digits = re.sub(r"\D", "", match.group("count"))
        products.append(
            RakutenProduct(
                name=match.group("name"),
                price=int(price_digits) if price_digits else 0,
                url=match.group("url"),
                image_url=match.group("img"),
                review_average=float(match.group("review")),
                review_count=int(count_digits) if count_digits else 0,
            )
        )
    return products


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


def update_posts(targets: Sequence[PostTarget]) -> None:
    """Update the selected WordPress posts."""
    settings = load_settings()
    provider = WordPressProvider(
        site_url=settings.wordpress_url,
        username=settings.wordpress_username,
        app_password=settings.wordpress_app_password,
    )
    service = WordPressPostService(provider)
    seo_service = SeoService()
    product_cache: dict[Path, list[RakutenProduct]] = {}

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
                    product_source
                )
                print(
                    f"Parsed {len(product_cache[product_source])} products from "
                    f"{product_source.relative_to(PROJECT_ROOT).as_posix()}"
                )
            article_products = product_cache[product_source]

        markdown_content = markdown_path.read_text(encoding="utf-8")
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
