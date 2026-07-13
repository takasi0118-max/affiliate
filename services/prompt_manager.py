"""Prompt template management service."""

from pathlib import Path
from string import Formatter

from config.settings import PROJECT_ROOT


class PromptManager:
    """Load and render prompt templates from prompts directories."""

    def __init__(self, site_key: str) -> None:
        """Initialize prompt paths for common and site-specific prompts."""
        # common_dirには全サイト共通のSEO/構成指示を置く。
        # site_dirにはdisasterなど、そのサイト専用の記事指示を置く。
        self.site_key = site_key
        self.common_dir = PROJECT_ROOT / "prompts" / "common"
        self.site_dir = PROJECT_ROOT / "prompts" / site_key

    def load_common_prompt(self, prompt_name: str) -> str:
        """Load a common prompt template by file stem."""
        return self._load_prompt(self.common_dir / f"{prompt_name}.md")

    def load_site_prompt(self, prompt_name: str) -> str:
        """Load a site-specific prompt template by file stem."""
        return self._load_prompt(self.site_dir / f"{prompt_name}.md")

    def build_prompt(
        self,
        prompt_name: str,
        variables: dict[str, str],
        include_seo: bool = True,
        include_structure: bool = True,
    ) -> str:
        """Build a rendered prompt from common and site-specific templates."""
        # 全記事共通のSEO指示と構成指示を先に読み込み、サイト別指示を後ろに重ねる。
        # 例: seo.md + article_structure.md + disaster/problem_article.md の順に結合する。
        prompt_parts: list[str] = []

        if include_seo:
            prompt_parts.append(self.load_common_prompt("seo"))
        if include_structure:
            prompt_parts.append(self.load_common_prompt("article_structure"))

        prompt_parts.append(self.load_site_prompt(prompt_name))
        # --- で区切ると、Geminiに渡す指示文のまとまりが見やすくなる。
        template = "\n\n---\n\n".join(prompt_parts)

        # テンプレート内の{theme}などが不足していないか、生成前に検査する。
        self._validate_variables(template, variables)
        return template.format(**variables)

    def list_site_prompts(self) -> list[str]:
        """Return available site prompt names."""
        # prompts/{site_key}/配下にあるMarkdownファイル名を記事テンプレート一覧として扱う。
        if not self.site_dir.exists():
            raise FileNotFoundError(f"Prompt directory not found: {self.site_dir}")

        return sorted(path.stem for path in self.site_dir.glob("*.md"))

    @staticmethod
    def _load_prompt(path: Path) -> str:
        """Load a prompt template file."""
        # ファイルが無いまま進むとGeminiへ空の指示を送る恐れがあるため、先に止める。
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _validate_variables(template: str, variables: dict[str, str]) -> None:
        """Validate that all template variables are provided."""
        # string.Formatterでテンプレート中の差し込み変数名だけを抽出する。
        required_names = {
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name
        }
        missing_names = required_names - variables.keys()
        if missing_names:
            missing = ", ".join(sorted(missing_names))
            raise ValueError(f"Missing prompt variables: {missing}")
