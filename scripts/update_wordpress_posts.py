"""Update existing WordPress posts from saved Markdown files."""

from __future__ import annotations

import re
from pathlib import Path

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


def main() -> None:
    settings = load_settings()
    provider = WordPressProvider(
        site_url=settings.wordpress_url,
        username=settings.wordpress_username,
        app_password=settings.wordpress_app_password,
    )
    service = WordPressPostService(provider)
    seo_service = SeoService()
    products = parse_products_from_markdown(PRODUCT_MD)

    updates = [
        (8, "problem", Path("sites/disaster/output/problem-emergency-backpack-how-to-choose.md"), products),
        (9, "product", Path("sites/disaster/output/product-bousai-rucksack-select.md"), None),
        (10, "ranking", Path("sites/disaster/output/ranking-bousai-backpack-ranking.md"), None),
    ]

    provider.test_connection()
    print("WordPress connection: OK")
    print(f"Parsed {len(products)} products for problem article")

    for post_id, article_type, path, article_products in updates:
        markdown_content = path.read_text(encoding="utf-8")
        seo = seo_service.analyze_article(markdown_content)
        updated_id = service.update_post_with_markdown(
            post_id=post_id,
            markdown_content=markdown_content,
            seo=seo,
            article_type=article_type,
            products=article_products,
        )
        post = provider.get_post(updated_id)
        title = post.get("title", {}).get("rendered", "")
        print(
            f"Post {updated_id} ({article_type}): updated, "
            f"status={post.get('status')}, title={title}"
        )


if __name__ == "__main__":
    main()
