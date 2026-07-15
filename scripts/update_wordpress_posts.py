"""Update existing WordPress posts from saved Markdown files.

Usage:
    python scripts/update_wordpress_posts.py
    python scripts/update_wordpress_posts.py 9
    python scripts/update_wordpress_posts.py 8 10
    python scripts/update_wordpress_posts.py --list
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from providers.rakuten_provider import RakutenProduct
from providers.wordpress_provider import WordPressProvider
from services.seo_service import SeoService
from services.wordpress_post_service import WordPressPostService

PRODUCT_MD = Path("sites/disaster/output/product-bousai-rucksack-select.md")

PRODUCT_BLOCK_PATTERN = re.compile(
    r"\[!\[(?P<name>[^\]]+)\]\((?P<img>[^)]+)\)\]\((?P<url>[^)]+)\)\s*\n\s*\n"
    r"\*\s+\*\*価格\*\*:\s*(?P<price>[^\n]+)\n"
    r"\*\s+\*\*レビュー評価\*\*:\s*(?P<review>[0-9.]+)[^\n]*件数:\s*(?P<count>[0-9,]+)件",
    re.S,
)


@dataclass(frozen=True)
class PostTarget:
    """One WordPress post and its source Markdown file."""

    post_id: int
    article_type: str
    markdown_path: Path
    needs_products: bool = False


POST_TARGETS: dict[int, PostTarget] = {
    8: PostTarget(
        8,
        "problem",
        Path("sites/disaster/output/problem-emergency-backpack-how-to-choose.md"),
        needs_products=True,
    ),
    9: PostTarget(
        9,
        "product",
        Path("sites/disaster/output/product-bousai-rucksack-select.md"),
    ),
    10: PostTarget(
        10,
        "ranking",
        Path("sites/disaster/output/ranking-bousai-backpack-ranking.md"),
    ),
}


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


def resolve_targets(post_ids: Sequence[int]) -> list[PostTarget]:
    """Return the post targets selected on the command line."""
    if not post_ids:
        return [POST_TARGETS[post_id] for post_id in sorted(POST_TARGETS)]

    unknown_ids = [post_id for post_id in post_ids if post_id not in POST_TARGETS]
    if unknown_ids:
        known = ", ".join(str(post_id) for post_id in sorted(POST_TARGETS))
        unknown = ", ".join(str(post_id) for post_id in unknown_ids)
        raise SystemExit(f"Unknown post ID(s): {unknown}. Registered IDs: {known}")

    return [POST_TARGETS[post_id] for post_id in post_ids]


def print_registered_posts() -> None:
    """Print the registered post mapping."""
    for post_id in sorted(POST_TARGETS):
        target = POST_TARGETS[post_id]
        print(
            f"{post_id}: {target.article_type} -> {target.markdown_path.as_posix()}"
        )


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

    products: list[RakutenProduct] | None = None
    if any(target.needs_products for target in targets):
        products = parse_products_from_markdown(PRODUCT_MD)
        print(f"Parsed {len(products)} products for problem article")

    provider.test_connection()
    print("WordPress connection: OK")

    for target in targets:
        markdown_path = PROJECT_ROOT / target.markdown_path
        if not markdown_path.exists():
            raise SystemExit(f"Markdown file not found: {markdown_path}")

        markdown_content = markdown_path.read_text(encoding="utf-8")
        seo = seo_service.analyze_article(markdown_content)
        article_products = products if target.needs_products else None
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

    if args.list:
        print_registered_posts()
        return

    targets = resolve_targets(args.post_ids)
    update_posts(targets)


if __name__ == "__main__":
    main()
