"""Article generation service using prompt templates and Gemini."""

from dataclasses import dataclass

from providers.gemini_provider import GeminiProvider
from services.prompt_manager import PromptManager


@dataclass(frozen=True)
class GeneratedArticle:
    """Generated article content with basic article metadata."""

    # themeは、themes.txtから選ばれた記事テーマ。
    theme: str
    # article_typeはproblem/product/rankingのような記事種別。
    article_type: str
    # contentはGeminiが生成したMarkdown本文。
    content: str

    @property
    def character_count(self) -> int:
        """Return the number of characters in the generated article."""
        return len(self.content)

    @property
    def is_generated(self) -> bool:
        """Return whether the article body was generated."""
        return bool(self.content.strip())


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
    ) -> GeneratedArticle:
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
        product_order: str,
    ) -> GeneratedArticle:
        """Generate a product introduction article."""
        # 商品紹介記事は、楽天商品を個別に説明して購入判断を助ける記事。
        return self._generate_article(
            prompt_name="product_article",
            article_type="product",
            theme=theme,
            category=category,
            tags=tags,
            products=products,
            extra_variables={"product_order": product_order},
        )

    def generate_ranking_article(
        self,
        theme: str,
        category: str,
        tags: list[str],
        products: str,
        ranking_order: str,
    ) -> GeneratedArticle:
        """Generate a comparison ranking article."""
        # 比較記事は、複数商品をランキングや表で比べる購入直前向けの記事。
        return self._generate_article(
            prompt_name="ranking_article",
            article_type="ranking",
            theme=theme,
            category=category,
            tags=tags,
            products=products,
            extra_variables={"ranking_order": ranking_order},
        )

    def _generate_article(
        self,
        prompt_name: str,
        article_type: str,
        theme: str,
        category: str,
        tags: list[str],
        products: str,
        extra_variables: dict[str, str] | None = None,
    ) -> GeneratedArticle:
        """Build a prompt and generate an article from it."""
        # 共通SEO指示、共通記事構成、サイト別プロンプトを結合して最終プロンプトを作る。
        # variablesの値が、prompt内の{theme}や{products}に差し込まれる。
        variables = {
            "theme": theme,
            "article_type": article_type,
            "category": category,
            "tags": ", ".join(tags),
            "products": products,
            "product_order": "",
            "ranking_order": "",
        }
        if extra_variables:
            variables.update(extra_variables)
        prompt = self.prompt_manager.build_prompt(
            prompt_name=prompt_name,
            variables=variables,
        )
        # Providerを経由してLLMへの通信を隠蔽し、記事生成サービス側は本文だけ受け取る。
        content = self.gemini_provider.generate_text(prompt)
        return GeneratedArticle(
            theme=theme,
            article_type=article_type,
            content=content,
        )
