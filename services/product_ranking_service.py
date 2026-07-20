"""Rank Rakuten products and build consistent theme product sets."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from providers.rakuten_provider import RakutenProduct, RakutenProvider


CATEGORY_ORDER = {
    "1人用": 0,
    "2人用": 1,
    "家族用": 2,
    "キャリー": 3,
    "その他": 4,
}


@dataclass(frozen=True)
class RankedProduct:
    """One product with ranking metadata for article generation."""

    rank: int
    name: str
    price: int
    url: str
    image_url: str | None
    review_average: float | None
    review_count: int | None
    score: float
    category: str

    @classmethod
    def from_product(cls, rank: int, product: RakutenProduct, score: float) -> RankedProduct:
        """Build ranked product metadata from a Rakuten product."""
        return cls(
            rank=rank,
            name=product.name,
            price=product.price,
            url=product.url,
            image_url=product.image_url,
            review_average=product.review_average,
            review_count=product.review_count,
            score=score,
            category=_detect_category(product.name),
        )

    def to_rakuten_product(self) -> RakutenProduct:
        """Return the underlying Rakuten product shape."""
        return RakutenProduct(
            name=self.name,
            price=self.price,
            url=self.url,
            image_url=self.image_url,
            review_average=self.review_average,
            review_count=self.review_count,
        )


@dataclass(frozen=True)
class ThemeProductSet:
    """Shared product pool and ranking order for one theme."""

    theme: str
    keyword: str
    products: tuple[RankedProduct, ...]
    ranking_top5: tuple[RankedProduct, ...]
    product_display_order: tuple[RankedProduct, ...]

    @property
    def all_products(self) -> list[RakutenProduct]:
        """Return all products as RakutenProduct objects."""
        return [product.to_rakuten_product() for product in self.products]

    @property
    def top5_products(self) -> list[RakutenProduct]:
        """Return top 5 products as RakutenProduct objects."""
        return [product.to_rakuten_product() for product in self.ranking_top5]


def build_theme_product_set(
    theme: str,
    keyword: str,
    products: list[RakutenProduct],
    *,
    pool_size: int = 10,
    ranking_size: int = 5,
) -> ThemeProductSet:
    """Score products, pick top ranks, and derive a non-ranking display order."""
    pool = products[:pool_size]
    if len(pool) < ranking_size:
        raise ValueError(
            f"Need at least {ranking_size} products, but only {len(pool)} were provided."
        )

    scored = sorted(
        (
            (product, _score_product(product))
            for product in pool
        ),
        key=lambda item: (-item[1], item[0].name),
    )
    ranked = tuple(
        RankedProduct.from_product(rank=index, product=product, score=score)
        for index, (product, score) in enumerate(scored, start=1)
    )
    ranking_top5 = ranked[:ranking_size]
    product_display_order = _build_product_display_order(ranked)
    return ThemeProductSet(
        theme=theme,
        keyword=keyword,
        products=ranked,
        ranking_top5=ranking_top5,
        product_display_order=product_display_order,
    )


def fetch_theme_product_set(
    rakuten_provider: RakutenProvider,
    theme: str,
    keyword: str,
    *,
    hits: int = 10,
    pool_size: int = 10,
    ranking_size: int = 5,
) -> ThemeProductSet:
    """Fetch products from Rakuten and build a ranked theme set."""
    products = rakuten_provider.search_items(keyword=keyword, hits=hits)
    return build_theme_product_set(
        theme=theme,
        keyword=keyword,
        products=products,
        pool_size=pool_size,
        ranking_size=ranking_size,
    )


def save_theme_product_set(path: Path, product_set: ThemeProductSet) -> None:
    """Persist a theme product set as JSON."""
    payload = {
        "theme": product_set.theme,
        "keyword": product_set.keyword,
        "products": [asdict(product) for product in product_set.products],
        "ranking_top5": [product.rank for product in product_set.ranking_top5],
        "product_display_order": [product.rank for product in product_set.product_display_order],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_theme_product_set(path: Path) -> ThemeProductSet:
    """Load a theme product set from JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    ranked = tuple(RankedProduct(**item) for item in payload["products"])
    by_rank = {product.rank: product for product in ranked}
    ranking_top5 = tuple(by_rank[rank] for rank in payload["ranking_top5"])
    product_display_order = tuple(by_rank[rank] for rank in payload["product_display_order"])
    return ThemeProductSet(
        theme=str(payload["theme"]),
        keyword=str(payload["keyword"]),
        products=ranked,
        ranking_top5=ranking_top5,
        product_display_order=product_display_order,
    )


def format_products_for_prompt(
    products: list[RankedProduct] | list[RakutenProduct],
    *,
    label: str = "商品",
) -> str:
    """Format products for Gemini prompts."""
    lines: list[str] = []
    for index, product in enumerate(products, start=1):
        if isinstance(product, RankedProduct):
            ranked = product
            review = _format_review(ranked.review_average, ranked.review_count)
            lines.append(
                "\n".join(
                    [
                        f"{index}. {ranked.name}",
                        f"   - 比較ランキング順位: {ranked.rank}位",
                        f"   - カテゴリ: {ranked.category}",
                        f"   - 価格: {ranked.price:,}円",
                        f"   - {review}",
                    ]
                )
            )
            continue

        review = _format_review(product.review_average, product.review_count)
        lines.append(
            "\n".join(
                [
                    f"{index}. {product.name}",
                    f"   - 価格: {product.price:,}円",
                    f"   - {review}",
                ]
            )
        )
    return "\n\n".join(lines)


def _score_product(product: RakutenProduct) -> float:
    """Return a deterministic ranking score."""
    average = product.review_average or 0.0
    count = product.review_count or 0
    confidence = min(1.0, math.log10(count + 1) / 3)
    low_review_penalty = 0.75 if count < 10 else 1.0
    return average * confidence * low_review_penalty


def _build_product_display_order(
    ranked_products: tuple[RankedProduct, ...],
) -> tuple[RankedProduct, ...]:
    """Return a product article order that differs from ranking order."""
    return tuple(
        sorted(
            ranked_products,
            key=lambda product: (
                CATEGORY_ORDER.get(product.category, 99),
                product.price,
                product.name,
            ),
        )
    )


def _detect_category(name: str) -> str:
    """Guess a display category from the product name."""
    if "1人" in name or "1人用" in name or "単身" in name:
        return "1人用"
    if "2人" in name or "2人用" in name or "夫婦" in name or "カップル" in name:
        return "2人用"
    if "家族" in name or "3人" in name or "4人" in name:
        return "家族用"
    if "キャリー" in name or "転がす" in name:
        return "キャリー"
    return "その他"


def _format_review(review_average: float | None, review_count: int | None) -> str:
    """Return a readable review summary."""
    if review_average is None or review_count is None:
        return "レビュー情報なし"
    return f"レビュー平均: {review_average} / 件数: {review_count:,}件"


def theme_product_set_path(output_dir: Path, theme: str) -> Path:
    """Return the JSON path for one theme's shared product catalog."""
    slug = re.sub(r"\s+", "-", theme.strip())
    return output_dir / f"product-set-{slug}.json"


def format_product_names_list(
    products: tuple[RankedProduct, ...] | list[RankedProduct],
) -> str:
    """Return numbered product names for Gemini prompts."""
    return "\n".join(
        f"{index}. {product.name}"
        for index, product in enumerate(products, start=1)
    )


def format_problem_reference_products(product_set: ThemeProductSet) -> str:
    """Format all products as reference text for problem articles."""
    return format_products_for_prompt(list(product_set.products))


def format_product_article_prompt(product_set: ThemeProductSet) -> str:
    """Format product details and display order for product articles."""
    return "\n\n".join(
        [
            "【紹介順（10商品）】",
            format_products_for_prompt(list(product_set.product_display_order)),
            "【参考: 比較ランキング上位5】",
            format_products_for_prompt(list(product_set.ranking_top5)),
        ]
    )


def format_ranking_article_prompt(product_set: ThemeProductSet) -> str:
    """Format ranked top 5 products for ranking articles."""
    return format_products_for_prompt(list(product_set.ranking_top5))
