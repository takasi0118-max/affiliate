"""Build Markdown product blocks and inject affiliate links."""

from __future__ import annotations

import re
from pathlib import Path

from providers.rakuten_provider import RakutenProvider
from services.markdown_product_block_service import (
    ProductBlock,
    count_affiliate_image_links,
    inject_missing_product_blocks,
    normalize_product_detail_sections,
    normalize_product_price_lines,
    sync_product_section_metadata,
)
from services.product_ranking_service import (
    RankedProduct,
    ThemeProductSet,
    fetch_theme_product_set,
    load_theme_product_set,
    save_theme_product_set,
    theme_product_set_path,
)


MIN_PRODUCT_BLOCKS_BY_TYPE = {
    "product": 10,
    "ranking": 5,
}
AFFILIATE_URL_MARKER = "hb.afl.rakuten.co.jp"


class ProductBlocksError(Exception):
    """Raised when required Rakuten affiliate blocks are missing."""


def build_product_block(product: RankedProduct) -> ProductBlock:
    """Return one affiliate product block."""
    price_text = f"{product.price:,}円（税込）"
    return ProductBlock(
        name=product.name,
        url=product.url,
        image_url=product.image_url or "",
        price=price_text,
        review_average=str(product.review_average) if product.review_average else None,
        review_count=f"{product.review_count:,}" if product.review_count else None,
    )


def inject_product_blocks_for_sections(
    content: str,
    products: list[RankedProduct],
    *,
    is_ranking: bool = False,
) -> str:
    """Inject Rakuten blocks and sync price/review metadata for product sections."""
    blocks = [build_product_block(product) for product in products]
    content = normalize_product_detail_sections(content)
    content = normalize_product_price_lines(content)
    content = inject_missing_product_blocks(content, blocks)
    return sync_product_section_metadata(content, products, is_ranking=is_ranking)


def inject_and_validate_affiliate_blocks(
    content: str,
    products: list[RankedProduct],
    article_type: str,
) -> str:
    """Inject affiliate blocks and fail when the minimum count is not met."""
    minimum = MIN_PRODUCT_BLOCKS_BY_TYPE.get(article_type)
    if minimum is None:
        return content

    _require_product_assets(products, article_type)
    updated = inject_product_blocks_for_sections(
        content,
        products,
        is_ranking=article_type == "ranking",
    )
    _require_affiliate_block_count(updated, article_type, minimum)
    return updated


def ensure_affiliate_blocks_for_article(
    content: str,
    product_set: ThemeProductSet,
    article_type: str,
    *,
    output_dir: Path,
    rakuten_provider: RakutenProvider | None = None,
    allow_refetch: bool = True,
) -> tuple[str, ThemeProductSet]:
    """Ensure affiliate blocks exist, refetching Rakuten once when needed."""
    minimum = MIN_PRODUCT_BLOCKS_BY_TYPE.get(article_type)
    if minimum is None:
        return content, product_set

    products = _products_for_article_type(product_set, article_type)
    try:
        return (
            inject_and_validate_affiliate_blocks(content, products, article_type),
            product_set,
        )
    except ProductBlocksError as first_error:
        if not allow_refetch or rakuten_provider is None:
            raise

    refreshed = fetch_theme_product_set(
        rakuten_provider,
        theme=product_set.theme,
        keyword=product_set.keyword,
        hits=10,
    )
    save_theme_product_set(theme_product_set_path(output_dir, product_set.theme), refreshed)
    products = _products_for_article_type(refreshed, article_type)
    try:
        return (
            inject_and_validate_affiliate_blocks(content, products, article_type),
            refreshed,
        )
    except ProductBlocksError as second_error:
        raise ProductBlocksError(
            f"{article_type} article still lacks Rakuten affiliate blocks after refetch. "
            f"{second_error}"
        ) from first_error


def ensure_affiliate_blocks_for_theme_markdown(
    content: str,
    theme: str,
    article_type: str,
    *,
    output_dir: Path,
    rakuten_provider: RakutenProvider | None = None,
) -> tuple[str, ThemeProductSet | None]:
    """Repair saved Markdown using the theme catalog, refetching Rakuten if needed."""
    minimum = MIN_PRODUCT_BLOCKS_BY_TYPE.get(article_type)
    if minimum is None:
        return content, None

    catalog_path = theme_product_set_path(output_dir, theme)
    product_set = load_theme_product_set(catalog_path) if catalog_path.exists() else None
    if product_set is None:
        if rakuten_provider is None:
            raise ProductBlocksError(
                f"No saved product catalog for theme '{theme}' and Rakuten refetch is unavailable."
            )
        product_set = fetch_theme_product_set(
            rakuten_provider,
            theme=theme,
            keyword=theme,
            hits=10,
        )
        save_theme_product_set(catalog_path, product_set)

    updated, product_set = ensure_affiliate_blocks_for_article(
        content,
        product_set,
        article_type,
        output_dir=output_dir,
        rakuten_provider=rakuten_provider,
        allow_refetch=True,
    )
    return updated, product_set


def _products_for_article_type(
    product_set: ThemeProductSet,
    article_type: str,
) -> list[RankedProduct]:
    """Return the product list used for one article type."""
    if article_type == "ranking":
        return list(product_set.ranking_top5)
    if article_type == "product":
        return list(product_set.product_display_order)
    return []


def _product_has_affiliate_assets(product: RankedProduct) -> bool:
    """Return whether one product has a usable affiliate URL and image."""
    return bool(
        product.url
        and AFFILIATE_URL_MARKER in product.url
        and product.image_url
    )


def _require_product_assets(products: list[RankedProduct], article_type: str) -> None:
    """Raise when Rakuten products are missing affiliate URLs or images."""
    missing = [product.name for product in products if not _product_has_affiliate_assets(product)]
    if not missing:
        return
    preview = " / ".join(missing[:3])
    suffix = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
    raise ProductBlocksError(
        f"{article_type} article cannot build affiliate blocks because Rakuten data "
        f"is incomplete for: {preview}{suffix}"
    )


def _require_affiliate_block_count(
    content: str,
    article_type: str,
    minimum: int,
) -> None:
    """Raise when Markdown does not contain enough affiliate image links."""
    actual = count_affiliate_image_links(content)
    if actual >= minimum:
        return
    raise ProductBlocksError(
        f"{article_type} article requires at least {minimum} Rakuten affiliate image links, "
        f"but only {actual} were found after injection."
    )


def _short_product_name(name: str) -> str:
    """Return a shorter alt text for product images."""
    cleaned = re.sub(r"\s+", " ", name).strip()
    if len(cleaned) <= 48:
        return cleaned
    return cleaned[:45] + "..."
