"""Markdown saving service for generated articles."""

from dataclasses import dataclass
from pathlib import Path

from services.article_generator import GeneratedArticle
from services.internal_link_service import LinkedArticleSet
from services.seo_service import SeoAnalysis
from services.theme_path_service import (
    article_markdown_path,
    article_slug,
    problem_only_markdown_path,
    resolve_theme_slug,
)
from utils.file_io import write_text_file


@dataclass(frozen=True)
class SavedArticle:
    """Saved Markdown file information for one generated article."""

    # article_typeはproblem/product/rankingのどの記事を保存したかを表す。
    article_type: str
    # pathは実際に保存したMarkdownファイルの場所。
    path: Path


@dataclass(frozen=True)
class MarkdownSaveResult:
    """Saved Markdown file information for one article set."""

    problem: SavedArticle
    product: SavedArticle
    ranking: SavedArticle

    @property
    def count(self) -> int:
        """Return the number of saved Markdown files."""
        return 3

    @property
    def is_ready(self) -> bool:
        """Return whether all expected Markdown files were saved."""
        return all(
            [
                self.problem.path.exists(),
                self.product.path.exists(),
                self.ranking.path.exists(),
            ]
        )


class MarkdownService:
    """Save generated articles as Markdown files."""

    def save_article_set(
        self,
        articles: LinkedArticleSet,
        problem_seo: SeoAnalysis,
        product_seo: SeoAnalysis,
        ranking_seo: SeoAnalysis,
        output_dir: Path,
        site_dir: Path | None = None,
    ) -> MarkdownSaveResult:
        """Save problem, product, and ranking articles to Markdown files."""
        site_dir = site_dir or output_dir.parent
        theme = articles.problem_article.theme
        theme_slug = resolve_theme_slug(theme, site_dir)
        problem = self.save_article(
            articles.problem_article,
            problem_seo,
            output_dir,
            theme_slug=theme_slug,
        )
        product = self.save_article(
            articles.product_article,
            product_seo,
            output_dir,
            theme_slug=theme_slug,
        )
        ranking = self.save_article(
            articles.ranking_article,
            ranking_seo,
            output_dir,
            theme_slug=theme_slug,
        )
        return MarkdownSaveResult(problem=problem, product=product, ranking=ranking)

    def save_article(
        self,
        article: GeneratedArticle,
        seo: SeoAnalysis,
        output_dir: Path,
        *,
        theme_slug: str | None = None,
        site_dir: Path | None = None,
    ) -> SavedArticle:
        """Save one generated article to a Markdown file."""
        if theme_slug is None:
            site_dir = site_dir or output_dir.parent
            theme_slug = resolve_theme_slug(article.theme, site_dir)
        slug = article_slug(article.article_type, theme_slug)
        if article.article_type == "problem_only":
            path = problem_only_markdown_path(output_dir, theme_slug)
        else:
            path = article_markdown_path(output_dir, theme_slug, article.article_type)
        write_text_file(path, _build_markdown_content(article, seo, slug))
        return SavedArticle(article_type=article.article_type, path=path)


def _build_markdown_content(
    article: GeneratedArticle,
    seo: SeoAnalysis,
    slug: str,
) -> str:
    """Build Markdown content with a small metadata header."""
    # slugはファイル名と同じ値に固定し、WordPress URLと出力名を一致させる。
    metadata = "\n".join(
        [
            "---",
            f"theme: {article.theme}",
            f"article_type: {article.article_type}",
            f"seo_title: {seo.seo_title}",
            f"meta_description: {seo.meta_description}",
            f"slug: {slug}",
            "---",
            "",
        ]
    )
    return f"{metadata}{article.content.strip()}\n"
