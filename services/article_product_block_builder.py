"""Build Markdown product blocks and inject affiliate links."""

from __future__ import annotations

import re

from services.markdown_product_block_service import (
    ProductBlock,
    inject_missing_product_blocks,
)
from services.product_ranking_service import RankedProduct


def build_product_block(product: RankedProduct) -> ProductBlock:
    """Return one affiliate product block."""
    price_text = f"{product.price:,}円（税込）"
    return ProductBlock(
        name=_short_product_name(product.name),
        url=product.url,
        image_url=product.image_url or "",
        price=price_text,
        review_average=str(product.review_average) if product.review_average else None,
        review_count=f"{product.review_count:,}" if product.review_count else None,
    )


def inject_product_blocks_for_sections(
    content: str,
    products: list[RankedProduct],
) -> str:
    """Inject Rakuten blocks into numbered product sections."""
    blocks = [build_product_block(product) for product in products]
    return inject_missing_product_blocks(content, blocks)


def _short_product_name(name: str) -> str:
    """Return a shorter alt text for product images."""
    cleaned = re.sub(r"\s+", " ", name).strip()
    if len(cleaned) <= 48:
        return cleaned
    return cleaned[:45] + "..."
