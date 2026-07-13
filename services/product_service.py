"""Product search and formatting service for article generation."""

from dataclasses import dataclass

from providers.rakuten_provider import RakutenProduct, RakutenProvider


@dataclass(frozen=True)
class ProductSearchResult:
    """Products and prompt text prepared for article generation."""

    # keywordは、どのテーマで楽天商品を検索したかを後で確認するために持つ。
    keyword: str
    # productsは、楽天APIから取得した商品データそのもの。
    products: list[RakutenProduct]
    # prompt_textは、Geminiへ渡しやすい日本語の箇条書きに整形した商品情報。
    prompt_text: str

    @property
    def count(self) -> int:
        """Return the number of fetched products."""
        return len(self.products)

    @property
    def has_products(self) -> bool:
        """Return whether at least one product was fetched."""
        return bool(self.products)


class ProductService:
    """Fetch Rakuten products and prepare them for prompts."""

    def __init__(self, rakuten_provider: RakutenProvider) -> None:
        """Initialize the service with a Rakuten provider."""
        # RakutenProviderはAPI通信担当、ProductServiceは記事用の整理担当。
        self.rakuten_provider = rakuten_provider

    def search_for_article(self, keyword: str, hits: int = 5) -> ProductSearchResult:
        """Search products and format them for article generation."""
        # テーマに関連する商品を楽天APIから取得する。
        products = self.rakuten_provider.search_items(keyword=keyword, hits=hits)
        # 取得した商品をGeminiのプロンプトに入れやすい文章へ変換する。
        prompt_text = self.format_products_for_prompt(products)
        return ProductSearchResult(
            keyword=keyword,
            products=products,
            prompt_text=prompt_text,
        )

    @staticmethod
    def format_products_for_prompt(products: list[RakutenProduct]) -> str:
        """Format products as readable Japanese text for Gemini prompts."""
        # 楽天APIから商品が返らなかった場合でも、Geminiに渡す文章は空にしない。
        # 空文字を渡すより「取得できなかった」と明示した方が、生成結果の意図が分かりやすい。
        if not products:
            return "楽天APIから関連商品を取得できませんでした。"

        # Geminiへ渡すため、商品オブジェクトを記事生成用の箇条書きテキストに整える。
        lines: list[str] = []
        for index, product in enumerate(products, start=1):
            # レビュー情報は商品によって無い場合があるため、初期値を用意しておく。
            review = "レビュー情報なし"
            if product.review_average is not None and product.review_count is not None:
                review = (
                    f"レビュー平均: {product.review_average} / "
                    f"件数: {product.review_count}"
                )

            # 1商品ごとに、記事内で使いやすい情報だけを日本語の箇条書きにする。
            lines.append(
                "\n".join(
                    [
                        f"{index}. {product.name}",
                        f"   - 価格: {product.price}円",
                        f"   - URL: {product.url}",
                        f"   - 画像URL: {product.image_url or 'なし'}",
                        f"   - {review}",
                    ]
                )
            )

        return "\n\n".join(lines)
