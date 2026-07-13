"""Application settings loaded from environment variables."""

from dataclasses import dataclass
from pathlib import Path
from typing import Final
import os

from dotenv import load_dotenv


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
ENV_PATH: Final[Path] = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class Settings:
    """Application-wide settings loaded from the .env file."""

    openai_api_key: str
    openai_model: str
    rakuten_application_id: str
    rakuten_access_key: str
    rakuten_affiliate_id: str
    wordpress_url: str
    wordpress_username: str
    wordpress_app_password: str
    site_key: str
    output_dir: Path
    log_level: str


def _get_required_env(name: str) -> str:
    """Return a required environment variable or raise a clear error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable is missing: {name}")
    return value


def load_settings() -> Settings:
    """Load application settings from .env."""
    load_dotenv(ENV_PATH)

    output_dir = PROJECT_ROOT / _get_required_env("OUTPUT_DIR")

    return Settings(
        openai_api_key=_get_required_env("OPENAI_API_KEY"),
        openai_model=_get_required_env("OPENAI_MODEL"),
        rakuten_application_id=_get_required_env("RAKUTEN_APPLICATION_ID"),
        rakuten_access_key=_get_required_env("RAKUTEN_ACCESS_KEY"),
        rakuten_affiliate_id=_get_required_env("RAKUTEN_AFFILIATE_ID"),
        wordpress_url=_get_required_env("WORDPRESS_URL"),
        wordpress_username=_get_required_env("WORDPRESS_USERNAME"),
        wordpress_app_password=_get_required_env("WORDPRESS_APP_PASSWORD"),
        site_key=_get_required_env("SITE_KEY"),
        output_dir=output_dir,
        log_level=_get_required_env("LOG_LEVEL"),
    )
