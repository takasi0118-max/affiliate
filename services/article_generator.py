"""Article generation service using prompt templates and Gemini."""

from providers.gemini_provider import GeminiProvider
from services.prompt_manager import PromptManager


class ArticleGenerator:
    """Generate affiliate articles for each article type."""

    def __init__(
        self,
        prompt_manager: PromptManager,
        gemini_provider: GeminiProvider,
    ) -> None:
        """Initialize the generator with prompt and Gemini services."""
        # PromptManagerは「指示文を作る係」、GeminiProviderは「Geminiへ送る係」。
        # ArticleGeneratorはその2つを組み合わせて、記事生成の窓口になる。
        self.prompt_manager = prompt_manager
        self.gemini_provider = gemini_provider

    def generate_problem_article(
        self,
        theme: str,
        category: str,
        tags: list[str],
        products: str,
    ) -> str:
        """Generate a problem-solving article."""
        # 悩み記事は、読者の不安や失敗例から解決策へつなげる集客用の記事。
        return self._generate_article(
            prompt_name="problem_article",
            article_type="problem",
            theme=theme,
            category=category,
            tags=tags,
            products=products,
        )

    def generate_product_article(
        self,
        theme: str,
        category: str,
        tags: list[str],
        products: str,
    ) -> str:
        """Generate a product introduction article."""
        # 商品紹介記事は、楽天商品を個別に説明して購入判断を助ける記事。
        return self._generate_article(
            prompt_name="product_article",
            article_type="product",
            theme=theme,
            category=category,
            tags=tags,
            products=products,
        )

    def generate_ranking_article(
        self,
        theme: str,
        category: str,
        tags: list[str],
        products: str,
    ) -> str:
        """Generate a comparison ranking article."""
        # 比較記事は、複数商品をランキングや表で比べる購入直前向けの記事。
        return self._generate_article(
            prompt_name="ranking_article",
            article_type="ranking",
            theme=theme,
            category=category,
            tags=tags,
            products=products,
        )

    def _generate_article(
        self,
        prompt_name: str,
        article_type: str,
        theme: str,
        category: str,
        tags: list[str],
        products: str,
    ) -> str:
        """Build a prompt and generate an article from it."""
        # 共通SEO指示、共通記事構成、サイト別プロンプトを結合して最終プロンプトを作る。
        # variablesの値が、prompt内の{theme}や{products}に差し込まれる。
        prompt = self.prompt_manager.build_prompt(
            prompt_name=prompt_name,
            variables={
                "theme": theme,
                "article_type": article_type,
                "category": category,
                "tags": ", ".join(tags),
                "products": products,
            },
        )
        # Providerを経由してLLMへの通信を隠蔽し、記事生成サービス側は本文だけ受け取る。
        return self.gemini_provider.generate_text(prompt)
