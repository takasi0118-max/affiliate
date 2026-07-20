"""Cross-article consistency validation using Gemini."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re

from providers.gemini_provider import GeminiProvider
from services.article_format_service import clean_generated_markdown
from services.article_generator import GeneratedArticle
from services.prompt_manager import PromptManager


logger = logging.getLogger(__name__)


class ArticleConsistencyError(Exception):
    """Raised when generated articles contain blocking contradictions."""

    def __init__(self, result: ArticleConsistencyResult) -> None:
        self.result = result
        issue_lines = "\n".join(
            f"- [{issue.severity}] {issue.category}: {issue.description}"
            for issue in result.blocking_issues
        )
        message = result.summary
        if issue_lines:
            message = f"{result.summary}\n{issue_lines}"
        super().__init__(message)


@dataclass(frozen=True)
class ConsistencyIssue:
    """One consistency issue reported by Gemini."""

    severity: str
    category: str
    description: str
    affected_articles: tuple[str, ...]

    @property
    def is_blocking(self) -> bool:
        """Return whether this issue should block article save."""
        return self.severity.lower() == "error"


@dataclass(frozen=True)
class ArticleConsistencyResult:
    """Result of a three-article consistency review."""

    theme: str
    is_consistent: bool
    summary: str
    issues: tuple[ConsistencyIssue, ...]
    raw_response: str

    @property
    def blocking_issues(self) -> tuple[ConsistencyIssue, ...]:
        """Return issues that must be fixed before saving."""
        return tuple(issue for issue in self.issues if issue.is_blocking)

    @property
    def warning_issues(self) -> tuple[ConsistencyIssue, ...]:
        """Return non-blocking warnings."""
        return tuple(issue for issue in self.issues if not issue.is_blocking)


class ArticleConsistencyService:
    """Validate that problem, product, and ranking articles do not contradict."""

    REVIEW_SYSTEM_INSTRUCTION = (
        "You are a meticulous Japanese affiliate content editor. "
        "Review article sets for factual and logical contradictions. "
        "Respond with JSON only."
    )

    def __init__(
        self,
        prompt_manager: PromptManager,
        gemini_provider: GeminiProvider,
    ) -> None:
        self.prompt_manager = prompt_manager
        self.gemini_provider = gemini_provider

    def validate_article_set(
        self,
        theme: str,
        problem_article: GeneratedArticle | str,
        product_article: GeneratedArticle | str,
        ranking_article: GeneratedArticle | str,
        products: str = "",
    ) -> ArticleConsistencyResult:
        """Ask Gemini to review three articles for contradictions."""
        prompt = self._render_consistency_prompt(
            theme=theme,
            products=products or "（商品リストなし）",
            problem_article=_article_body(problem_article),
            product_article=_article_body(product_article),
            ranking_article=_article_body(ranking_article),
        )
        logger.info("Running cross-article consistency check for theme: %s", theme)
        raw_response = self.gemini_provider.generate_text(
            prompt,
            temperature=0.2,
            system_instruction=self.REVIEW_SYSTEM_INSTRUCTION,
        )
        result = _parse_consistency_response(theme=theme, raw_response=raw_response)
        if result.blocking_issues:
            logger.error(
                "Article consistency check failed for theme %s: %s",
                theme,
                result.summary,
            )
        elif result.warning_issues:
            logger.warning(
                "Article consistency warnings for theme %s: %d item(s)",
                theme,
                len(result.warning_issues),
            )
        else:
            logger.info("Article consistency check passed for theme: %s", theme)
        return result

    def _render_consistency_prompt(
        self,
        *,
        theme: str,
        products: str,
        problem_article: str,
        product_article: str,
        ranking_article: str,
    ) -> str:
        """Fill the consistency prompt without interpreting other brace literals."""
        template = self.prompt_manager.load_common_prompt("article_consistency_check")
        replacements = {
            "theme": theme,
            "products": products,
            "problem_article": problem_article,
            "product_article": product_article,
            "ranking_article": ranking_article,
        }
        for key, value in replacements.items():
            template = template.replace("{" + key + "}", value)
        return template

    def require_consistent_article_set(
        self,
        theme: str,
        problem_article: GeneratedArticle | str,
        product_article: GeneratedArticle | str,
        ranking_article: GeneratedArticle | str,
        products: str = "",
    ) -> ArticleConsistencyResult:
        """Validate the article set and raise if blocking contradictions exist."""
        result = self.validate_article_set(
            theme=theme,
            problem_article=problem_article,
            product_article=product_article,
            ranking_article=ranking_article,
            products=products,
        )
        if not result.is_consistent or result.blocking_issues:
            raise ArticleConsistencyError(result)
        return result


def _article_body(article: GeneratedArticle | str) -> str:
    """Return cleaned article body text for review prompts."""
    content = article.content if isinstance(article, GeneratedArticle) else article
    return clean_generated_markdown(content)


def _parse_consistency_response(theme: str, raw_response: str) -> ArticleConsistencyResult:
    """Parse Gemini JSON response into a structured result."""
    payload = _extract_json_object(raw_response)
    issues: list[ConsistencyIssue] = []
    for item in payload.get("issues", []):
        if not isinstance(item, dict):
            continue
        affected = item.get("affected_articles", [])
        if isinstance(affected, str):
            affected = [affected]
        issues.append(
            ConsistencyIssue(
                severity=str(item.get("severity", "error")).strip().lower(),
                category=str(item.get("category", "未分類")).strip(),
                description=str(item.get("description", "")).strip(),
                affected_articles=tuple(str(name) for name in affected if name),
            )
        )

    blocking_issues = [issue for issue in issues if issue.is_blocking]
    is_consistent = bool(payload.get("is_consistent", not blocking_issues))
    if blocking_issues:
        is_consistent = False

    summary = str(payload.get("summary", "")).strip()
    if not summary:
        summary = (
            "3記事間に矛盾は見つかりませんでした。"
            if is_consistent
            else "3記事間に修正が必要な矛盾が見つかりました。"
        )

    return ArticleConsistencyResult(
        theme=theme,
        is_consistent=is_consistent,
        summary=summary,
        issues=tuple(issues),
        raw_response=raw_response,
    )


def _extract_json_object(text: str) -> dict:
    """Extract and parse a JSON object from Gemini output."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Gemini consistency check did not return JSON.")

    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as error:
        raise ValueError("Gemini consistency check returned invalid JSON.") from error

    if not isinstance(payload, dict):
        raise ValueError("Gemini consistency check JSON must be an object.")
    return payload
