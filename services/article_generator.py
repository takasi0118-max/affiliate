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
        return self.gemini_provider.generate_text(prompt)
