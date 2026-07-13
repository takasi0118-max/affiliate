"""Entry point for the affiliate article generation system."""

import logging

from config.settings import PROJECT_ROOT, load_settings
from config.site_config import load_site_config
from providers.rakuten_provider import RakutenApiError, RakutenProvider
from services.prompt_manager import PromptManager
from services.site_manager import SiteManager
from utils.logger import setup_logging


logger = logging.getLogger(__name__)


def main() -> None:
    """Run the application."""
    settings = load_settings()
    setup_logging(
        log_level=settings.log_level,
        log_file=PROJECT_ROOT / "logs" / "app.log",
    )

    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    site_manager = SiteManager(site_config)
    site_manager.ensure_output_dir()
    prompt_manager = PromptManager(site_config.site_key)
    available_prompts = prompt_manager.list_site_prompts()
    next_theme = site_manager.get_next_theme()
    rakuten_provider = RakutenProvider(
        application_id=settings.rakuten_application_id,
        access_key=settings.rakuten_access_key,
        affiliate_id=settings.rakuten_affiliate_id,
    )

    if next_theme is not None:
        rakuten_error = ""
        try:
            products = rakuten_provider.search_items(keyword=next_theme, hits=5)
        except RakutenApiError as error:
            logger.error("Rakuten API request failed: %s", error)
            products = []
            rakuten_error = str(error)

        sample_prompt = prompt_manager.build_prompt(
            prompt_name="problem_article",
            variables={
                "theme": next_theme,
                "article_type": "problem",
                "category": site_manager.get_default_category(),
                "tags": ", ".join(site_manager.get_default_tags()),
                "products": f"楽天APIから{len(products)}件の商品を取得済みです。",
            },
        )
    else:
        products = []
        rakuten_error = ""
        sample_prompt = ""

    logger.info("Configuration loaded for site: %s", site_config.site_key)
    print("Affiliate system prompt management is ready.")
    print(f"Site: {site_config.site_key}")
    print(f"Themes: {len(site_config.themes)}")
    print(f"Available themes: {len(site_manager.get_available_themes())}")
    print(f"Next theme available: {next_theme is not None}")
    print(f"Default category configured: {bool(site_manager.get_default_category())}")
    print(f"Default tags: {len(site_manager.get_default_tags())}")
    print(f"History records: {len(site_manager.history)}")
    print(f"Prompt templates: {len(available_prompts)}")
    print(f"Sample prompt built: {bool(sample_prompt)}")
    print(f"Rakuten products: {len(products)}")
    print(f"Rakuten connected: {not rakuten_error}")
    if rakuten_error:
        print(f"Rakuten error: {rakuten_error}")


if __name__ == "__main__":
    main()
