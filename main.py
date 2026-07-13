"""Entry point for the affiliate article generation system."""

import logging

from config.settings import PROJECT_ROOT, load_settings
from config.site_config import load_site_config
from google.genai import errors
from providers.gemini_provider import GeminiApiError, GeminiProvider
from providers.rakuten_provider import RakutenApiError, RakutenProduct, RakutenProvider
from services.article_generator import ArticleGenerator
from services.prompt_manager import PromptManager
from services.site_manager import SiteManager
from utils.logger import setup_logging


logger = logging.getLogger(__name__)


def _format_products_for_prompt(products: list[RakutenProduct]) -> str:
    """Format Rakuten products for article prompts."""
    if not products:
        return "楽天APIから関連商品を取得できませんでした。"

    lines: list[str] = []
    for index, product in enumerate(products, start=1):
        review = "レビュー情報なし"
        if product.review_average is not None and product.review_count is not None:
            review = f"レビュー平均: {product.review_average} / 件数: {product.review_count}"

        lines.append(
            "\n".join(
                [
                    f"{index}. {product.name}",
                    f"   - 価格: {product.price}円",
                    f"   - URL: {product.url}",
                    f"   - 画像URL: {product.image_url or 'なし'}",
                    f"   - {review}",
                ]
            )
        )

    return "\n\n".join(lines)


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
    gemini_provider = GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )
    article_generator = ArticleGenerator(
        prompt_manager=prompt_manager,
        gemini_provider=gemini_provider,
    )

    if next_theme is not None:
        rakuten_error = ""
        gemini_error = ""
        try:
            products = rakuten_provider.search_items(keyword=next_theme, hits=5)
        except RakutenApiError as error:
            logger.error("Rakuten API request failed: %s", error)
            products = []
            rakuten_error = str(error)

        try:
            sample_article = article_generator.generate_problem_article(
                theme=next_theme,
                category=site_manager.get_default_category(),
                tags=site_manager.get_default_tags(),
                products=_format_products_for_prompt(products),
            )
        except (GeminiApiError, errors.APIError) as error:
            logger.error("Gemini article generation failed: %s", error)
            sample_article = ""
            gemini_error = str(error)
    else:
        products = []
        rakuten_error = ""
        gemini_error = ""
        sample_article = ""

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
    print(f"Sample article generated: {bool(sample_article)}")
    print(f"Rakuten products: {len(products)}")
    print(f"Rakuten connected: {not rakuten_error}")
    if rakuten_error:
        print(f"Rakuten error: {rakuten_error}")
    print(f"Gemini connected: {not gemini_error}")
    if gemini_error:
        print(f"Gemini error: {gemini_error}")


if __name__ == "__main__":
    main()
