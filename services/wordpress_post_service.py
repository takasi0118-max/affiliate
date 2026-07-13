"""WordPress draft posting service for generated articles."""

from dataclasses import dataclass
import re

from providers.wordpress_provider import WordPressProvider
from services.article_generator import GeneratedArticle
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

    def create_draft_post_set(
        self,
        articles: LinkedArticleSet,
        problem_seo: SeoAnalysis,
        product_seo: SeoAnalysis,
        ranking_seo: SeoAnalysis,
    ) -> WordPressPostResult:
        """Create draft posts for problem, product, and ranking articles."""
        # STEP16では公開ではなく下書き作成までにし、管理画面で確認できる状態にする。
        problem = self.create_draft_post(articles.problem_article, problem_seo)
        product = self.create_draft_post(articles.product_article, product_seo)
        ranking = self.create_draft_post(articles.ranking_article, ranking_seo)
        return WordPressPostResult(problem=problem, product=product, ranking=ranking)

    def create_draft_post(
        self,
        article: GeneratedArticle,
        seo: SeoAnalysis,
    ) -> PostedArticle:
        """Create one WordPress draft post."""
        # SEOタイトルが読めない場合でも、テーマと記事種別から下書きタイトルを作る。
        title = seo.seo_title or _fallback_title(article)
        content = _clean_post_content(article.content)
        post_id = self.wordpress_provider.create_draft_post(
            title=title,
            content=content,
            slug=seo.slug,
            excerpt=seo.meta_description,
        )
        return PostedArticle(article_type=article.article_type, post_id=post_id)


def _clean_post_content(content: str) -> str:
    """Remove generated metadata wrappers before sending content to WordPress."""
    # WordPress本文には、管理用SEOメタ情報やMarkdownコードフェンスを入れない。
    lines = content.strip().splitlines()
    lines = _strip_json_metadata_block(lines)
    lines = _strip_wrapping_code_fence(lines)
    lines = _strip_front_matter_block(lines)
    lines = _strip_labeled_metadata_lines(lines)
    return "\n".join(lines).strip()


def _strip_wrapping_code_fence(lines: list[str]) -> list[str]:
    """Remove a full Markdown code fence wrapper when Gemini adds one."""
    if not lines:
        return lines

    first_line = lines[0].strip().lower()
    if first_line.startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return lines


def _strip_json_metadata_block(lines: list[str]) -> list[str]:
    """Remove a leading JSON metadata code block."""
    if not lines or not lines[0].strip().startswith("```json"):
        return lines

    for index, line in enumerate(lines[1:], start=1):
        if line.strip().startswith("```"):
            return lines[index + 1 :]
    return lines


def _strip_front_matter_block(lines: list[str]) -> list[str]:
    """Remove a leading YAML-like metadata block."""
    if not lines or lines[0].strip() != "---":
        return lines

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[index + 1 :]
    return lines


def _strip_labeled_metadata_lines(lines: list[str]) -> list[str]:
    """Remove leading SEO label lines such as 'SEOタイトル: ...'."""
    metadata_pattern = re.compile(
        r"^(seo\s*title|seoタイトル|タイトル|meta\s*description|メタディスクリプション|slug|スラッグ)\s*[:：]",
        flags=re.IGNORECASE,
    )

    index = 0
    while index < len(lines):
        stripped_line = lines[index].strip()
        if not stripped_line or stripped_line == "---":
            index += 1
            continue
        if metadata_pattern.match(stripped_line):
            index += 1
            continue
        break
    return lines[index:]


def _fallback_title(article: GeneratedArticle) -> str:
    """Return a readable fallback title when SEO title is missing."""
    labels = {
        "problem": "悩み解決記事",
        "product": "商品紹介記事",
        "ranking": "比較ランキング記事",
    }
    return f"{article.theme}の{labels.get(article.article_type, '記事')}"
