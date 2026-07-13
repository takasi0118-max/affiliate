"""Markdown saving service for generated articles."""

from dataclasses import dataclass
from pathlib import Path
import re

from services.article_generator import GeneratedArticle
from services.internal_link_service import LinkedArticleSet
from services.seo_service import SeoAnalysis
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
    ) -> MarkdownSaveResult:
        """Save problem, product, and ranking articles to Markdown files."""
        # STEP15では、生成済みの3記事を人が確認できるMarkdownファイルにする。
        problem = self.save_article(articles.problem_article, problem_seo, output_dir)
        product = self.save_article(articles.product_article, product_seo, output_dir)
        ranking = self.save_article(articles.ranking_article, ranking_seo, output_dir)
        return MarkdownSaveResult(problem=problem, product=product, ranking=ranking)

    def save_article(
        self,
        article: GeneratedArticle,
        seo: SeoAnalysis,
        output_dir: Path,
    ) -> SavedArticle:
        """Save one generated article to a Markdown file."""
        # slugがあればURLと同じ名前で保存し、無ければテーマと記事種別から仮名を作る。
        slug = _safe_slug(seo.slug or f"{article.theme}-{article.article_type}")
        path = output_dir / f"{article.article_type}-{slug}.md"
        write_text_file(path, _build_markdown_content(article, seo))
        return SavedArticle(article_type=article.article_type, path=path)


def _build_markdown_content(article: GeneratedArticle, seo: SeoAnalysis) -> str:
    """Build Markdown content with a small metadata header."""
    # 本文の先頭に管理用メタ情報を置くと、後で保存ファイルだけ見ても内容を判断しやすい。
    metadata = "\n".join(
        [
            "---",
            f"theme: {article.theme}",
            f"article_type: {article.article_type}",
            f"seo_title: {seo.seo_title}",
            f"meta_description: {seo.meta_description}",
            f"slug: {seo.slug}",
            "---",
            "",
        ]
    )
    return f"{metadata}{article.content.strip()}\n"


def _safe_slug(value: str) -> str:
    """Return a filesystem-safe slug."""
    # Windowsのファイル名で使えない文字をハイフンへ置き換える。
    # 日本語slugはそのまま残し、Geminiが日本語slugを返しても保存できるようにする。
    slug = value.strip().lower()
    slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    slug = slug.rstrip(". ")
    return slug or "article"
