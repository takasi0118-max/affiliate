"""Internal link generation service for related article sets."""

from dataclasses import dataclass, replace

from services.article_generator import GeneratedArticle
from services.article_link_sanitizer import sanitize_article_references
from services.seo_service import SeoAnalysis


@dataclass(frozen=True)
class ArticleLink:
    """Internal link information for one generated article."""

    # article_typeはproblem/product/rankingのどの記事へ向けたリンクかを表す。
    article_type: str
    # titleはリンクテキストとして表示する記事タイトル。
    title: str
    # urlはWordPress公開時に使う想定の内部URL。slugから作る。
    url: str

    def to_markdown(self) -> str:
        """Return the link as a Markdown list item."""
        return f"- [{self.title}]({self.url})"


@dataclass(frozen=True)
class LinkedArticleSet:
    """Generated articles after internal links are appended."""

    problem_article: GeneratedArticle
    product_article: GeneratedArticle
    ranking_article: GeneratedArticle
    link_count: int

    @property
    def is_ready(self) -> bool:
        """Return whether all expected internal links were created."""
        # 3記事が互いに他2記事へリンクするため、合計6リンクが最低条件。
        return self.link_count >= 6


class InternalLinkService:
    """Append internal links between problem, product, and ranking articles."""

    def apply_links(
        self,
        problem_article: GeneratedArticle,
        problem_seo: SeoAnalysis,
        product_article: GeneratedArticle,
        product_seo: SeoAnalysis,
        ranking_article: GeneratedArticle,
        ranking_seo: SeoAnalysis,
    ) -> LinkedArticleSet:
        """Append related-article links to all three articles."""
        # SEO解析で取り出したslug/titleを使い、保存や投稿前に内部リンクを確定する。
        links = {
            "problem": _build_link(problem_article, problem_seo),
            "product": _build_link(product_article, product_seo),
            "ranking": _build_link(ranking_article, ranking_seo),
        }

        linked_problem = _append_related_links(
            article=problem_article,
            links=[links["product"], links["ranking"]],
        )
        linked_product = _append_related_links(
            article=product_article,
            links=[links["problem"], links["ranking"]],
        )
        linked_ranking = _append_related_links(
            article=ranking_article,
            links=[links["problem"], links["product"]],
        )

        allowed_slugs = {
            slug
            for slug in (
                problem_seo.slug,
                product_seo.slug,
                ranking_seo.slug,
            )
            if slug
        }
        linked_problem = _sanitize_article(linked_problem, allowed_slugs)
        linked_product = _sanitize_article(linked_product, allowed_slugs)
        linked_ranking = _sanitize_article(linked_ranking, allowed_slugs)

        return LinkedArticleSet(
            problem_article=linked_problem,
            product_article=linked_product,
            ranking_article=linked_ranking,
            link_count=6,
        )


def _build_link(article: GeneratedArticle, seo: SeoAnalysis) -> ArticleLink:
    """Build link information from article metadata and SEO metadata."""
    # SEOタイトルが取れていればリンク文に使い、無ければ記事種別から分かる文言にする。
    title = seo.seo_title or _fallback_title(article.article_type, article.theme)
    # slugが取れていればWordPressの想定URLにする。無ければ記事種別で仮URLを作る。
    slug = seo.slug or f"{article.theme}-{article.article_type}"
    return ArticleLink(
        article_type=article.article_type,
        title=title,
        url=f"/{slug.strip('/')}/",
    )


def _append_related_links(
    article: GeneratedArticle,
    links: list[ArticleLink],
) -> GeneratedArticle:
    """Return an article with a related-article section appended."""
    # すでに関連記事セクションがある場合は、二重追加を避ける。
    if "## 関連記事" in article.content:
        return article

    related_section = "\n".join(
        [
            "",
            "## 関連記事",
            "",
            *[link.to_markdown() for link in links],
            "",
        ]
    )
    return replace(article, content=f"{article.content.rstrip()}\n{related_section}")


def _sanitize_article(
    article: GeneratedArticle,
    allowed_slugs: set[str],
) -> GeneratedArticle:
    """Remove references to articles outside the current article set."""
    sanitized_content = sanitize_article_references(article.content, allowed_slugs)
    return replace(article, content=sanitized_content)


def _fallback_title(article_type: str, theme: str) -> str:
    """Return a readable fallback title when SEO title is missing."""
    labels = {
        "problem": "悩み解決記事",
        "product": "商品紹介記事",
        "ranking": "比較ランキング記事",
    }
    return f"{theme}の{labels.get(article_type, '関連記事')}"
