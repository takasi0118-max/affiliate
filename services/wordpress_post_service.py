"""WordPress draft posting service for generated articles."""

from dataclasses import dataclass

from providers.rakuten_provider import RakutenProduct
from providers.wordpress_provider import WordPressProvider
from services.article_generator import GeneratedArticle
from services.article_format_service import ArticleFormatService, clean_generated_markdown
from services.internal_link_service import LinkedArticleSet
from services.seo_service import SeoAnalysis


@dataclass(frozen=True)
class PostedArticle:
    """WordPress draft post information for one generated article."""

    # article_typeはproblem/product/rankingのどの記事を投稿したかを表す。
    article_type: str
    # post_idはWordPressが作成した下書き投稿のID。
    post_id: int


@dataclass(frozen=True)
class WordPressPostResult:
    """WordPress draft post information for one article set."""

    problem: PostedArticle
    product: PostedArticle
    ranking: PostedArticle

    @property
    def count(self) -> int:
        """Return the number of created draft posts."""
        return 3

    @property
    def is_ready(self) -> bool:
        """Return whether all expected draft posts were created."""
        return all(
            [
                self.problem.post_id > 0,
                self.product.post_id > 0,
                self.ranking.post_id > 0,
            ]
        )


class WordPressPostService:
    """Create WordPress draft posts from generated articles."""

    def __init__(self, wordpress_provider: WordPressProvider) -> None:
        """Initialize the service with a WordPress API provider."""
        # ProviderがAPI通信を担当し、このServiceは3記事投稿の流れを担当する。
        self.wordpress_provider = wordpress_provider
        # ArticleFormatServiceは、Markdownを記事タイプ別HTMLへ整形する担当。
        self.article_format_service = ArticleFormatService()

    def create_draft_post_set(
        self,
        articles: LinkedArticleSet,
        problem_seo: SeoAnalysis,
        product_seo: SeoAnalysis,
        ranking_seo: SeoAnalysis,
        products: list[RakutenProduct] | None = None,
    ) -> WordPressPostResult:
        """Create draft posts for problem, product, and ranking articles."""
        # STEP16では公開ではなく下書き作成までにし、管理画面で確認できる状態にする。
        problem = self.create_draft_post(articles.problem_article, problem_seo, products)
        product = self.create_draft_post(articles.product_article, product_seo, products)
        ranking = self.create_draft_post(articles.ranking_article, ranking_seo, products)
        return WordPressPostResult(problem=problem, product=product, ranking=ranking)

    def create_draft_post(
        self,
        article: GeneratedArticle,
        seo: SeoAnalysis,
        products: list[RakutenProduct] | None = None,
    ) -> PostedArticle:
        """Create one WordPress draft post."""
        # SEOタイトルが読めない場合でも、テーマと記事種別から下書きタイトルを作る。
        title = seo.seo_title or _fallback_title(article)
        content = self.article_format_service.format_article(
            article_type=article.article_type,
            markdown_content=article.content,
            products=products,
        )
        post_id = self.wordpress_provider.create_draft_post(
            title=title,
            content=content,
            slug=seo.slug,
            excerpt=seo.meta_description,
        )
        return PostedArticle(article_type=article.article_type, post_id=post_id)

    def update_post_with_markdown(
        self,
        post_id: int,
        markdown_content: str,
        seo: SeoAnalysis,
        article_type: str = "default",
        products: list[RakutenProduct] | None = None,
    ) -> int:
        """Update an existing WordPress post with HTML converted from Markdown."""
        # 既存のMarkdownをHTML化し、作成済み下書きの本文だけを差し替える。
        html_content = self.article_format_service.format_article(
            article_type=article_type,
            markdown_content=markdown_content,
            products=products,
        )
        return self.wordpress_provider.update_post(
            post_id=post_id,
            content=html_content,
            title=seo.seo_title,
            slug=seo.slug,
            excerpt=seo.meta_description,
        )


def _clean_post_content(content: str) -> str:
    """Remove generated metadata wrappers before sending content to WordPress."""
    return clean_generated_markdown(content)


def markdown_to_wordpress_html(
    content: str,
    article_type: str = "default",
    products: list[RakutenProduct] | None = None,
) -> str:
    """Convert generated Markdown content into WordPress-friendly HTML."""
    return ArticleFormatService().format_article(article_type, content, products)


def _fallback_title(article: GeneratedArticle) -> str:
    """Return a readable fallback title when SEO title is missing."""
    labels = {
        "problem": "悩み解決記事",
        "product": "商品紹介記事",
        "ranking": "比較ランキング記事",
    }
    return f"{article.theme}の{labels.get(article.article_type, '記事')}"
