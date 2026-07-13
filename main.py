"""Entry point for the affiliate article generation system."""

import logging

import requests

from config.settings import PROJECT_ROOT, load_settings
from config.site_config import load_site_config
from google.genai import errors
from providers.gemini_provider import GeminiApiError, GeminiProvider
from providers.rakuten_provider import RakutenApiError, RakutenProvider
from providers.wordpress_provider import WordPressApiError, WordPressProvider
from services.article_generator import ArticleGenerator
from services.product_service import ProductService
from services.prompt_manager import PromptManager
from services.seo_service import SeoService
from services.site_manager import SiteManager
from utils.logger import setup_logging


logger = logging.getLogger(__name__)


def main() -> None:
    """Run the application."""
    # .envとサイト別設定を読み込み、以降の処理で使う共通サービスを準備する。
    # main.pyは「全体の司令塔」で、細かい処理は各ProviderやServiceに任せる。
    settings = load_settings()
    setup_logging(
        log_level=settings.log_level,
        log_file=PROJECT_ROOT / "logs" / "app.log",
    )

    # SITE_KEYに応じて、themes.txtやcategories.jsonなどサイト専用の設定を読み込む。
    site_config = load_site_config(
        site_key=settings.site_key,
        output_dir=settings.output_dir,
    )
    # SiteManagerはテーマの未処理判定や出力先フォルダ作成など、サイト運用を担当する。
    site_manager = SiteManager(site_config)
    site_manager.ensure_output_dir()
    # PromptManagerはMarkdownのプロンプトテンプレートを読み込み、変数を埋め込む担当。
    prompt_manager = PromptManager(site_config.site_key)
    available_prompts = prompt_manager.list_site_prompts()
    next_theme = site_manager.get_next_theme()
    # RakutenProviderは楽天APIとの通信だけを担当する。
    rakuten_provider = RakutenProvider(
        application_id=settings.rakuten_application_id,
        access_key=settings.rakuten_access_key,
        affiliate_id=settings.rakuten_affiliate_id,
    )
    # ProductServiceは楽天商品を取得し、記事生成で使いやすい文章へ整える担当。
    product_service = ProductService(rakuten_provider)
    # GeminiProviderはGemini APIとの通信だけを担当する。
    gemini_provider = GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
    )
    # ArticleGeneratorは「プロンプト作成」と「Geminiへの生成依頼」をまとめる担当。
    article_generator = ArticleGenerator(
        prompt_manager=prompt_manager,
        gemini_provider=gemini_provider,
    )
    # SeoServiceは、生成された記事にSEOタイトルやFAQが含まれているか確認する担当。
    seo_service = SeoService()
    # WordPressProviderはWordPress REST APIとの通信だけを担当する。
    # STEP08では安全のため投稿はせず、認証付きで接続できるかだけ確認する。
    wordpress_provider = WordPressProvider(
        site_url=settings.wordpress_url,
        username=settings.wordpress_username,
        app_password=settings.wordpress_app_password,
    )

    # 未処理テーマがある場合だけ、商品取得から記事生成までの確認処理を行う。
    wordpress_error = ""
    try:
        wordpress_provider.test_connection()
    except (WordPressApiError, requests.RequestException) as error:
        logger.error("WordPress API connection failed: %s", error)
        # WordPress接続に失敗しても、楽天/Geminiの確認結果は表示できるようにする。
        wordpress_error = str(error)

    if next_theme is not None:
        # エラー文字列を空で初期化しておき、失敗した時だけ内容を入れる。
        # 最後のprintで空かどうかを見れば、接続成功/失敗を判定できる。
        rakuten_error = ""
        gemini_error = ""
        try:
            # 記事テーマに関連する楽天商品を取得し、商品紹介の材料にする。
            product_result = product_service.search_for_article(
                keyword=next_theme,
                hits=5,
            )
            products = product_result.products
        except RakutenApiError as error:
            logger.error("Rakuten API request failed: %s", error)
            # 楽天APIが失敗しても、アプリ全体は止めずにGemini疎通確認へ進める。
            products = []
            product_result = None
            rakuten_error = str(error)

        try:
            # STEP11では、1テーマ目の正式な悩み記事を生成する。
            problem_article = article_generator.generate_problem_article(
                theme=next_theme,
                category=site_manager.get_default_category(),
                tags=site_manager.get_default_tags(),
                products=(
                    product_result.prompt_text
                    if product_result is not None
                    else ProductService.format_products_for_prompt(products)
                ),
            )
            # 生成した悩み記事からSEOメタ情報と見出し構成を読み取って確認する。
            seo_analysis = seo_service.analyze_article(problem_article.content)
        except (GeminiApiError, errors.APIError) as error:
            logger.error("Gemini article generation failed: %s", error)
            # Gemini側で失敗した場合も、原因をターミナルに表示するため文字列で保持する。
            problem_article = None
            gemini_error = str(error)
            seo_analysis = None
    else:
        # すべてのテーマが処理済みなら、API通信は行わずに結果表示だけ行う。
        products = []
        product_result = None
        rakuten_error = ""
        gemini_error = ""
        problem_article = None
        seo_analysis = None

    # 実行結果をターミナルへ出し、どこまで接続できたかを確認しやすくする。
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
    print(f"Problem article generated: {bool(problem_article and problem_article.is_generated)}")
    if problem_article is not None:
        print(f"Problem article type: {problem_article.article_type}")
        print(f"Problem article characters: {problem_article.character_count}")
    print(f"SEO ready: {bool(seo_analysis and seo_analysis.is_ready)}")
    if seo_analysis is not None:
        print(f"SEO title detected: {bool(seo_analysis.seo_title)}")
        print(f"Meta description detected: {bool(seo_analysis.meta_description)}")
        print(f"Slug detected: {bool(seo_analysis.slug)}")
        print(f"H2 headings: {seo_analysis.h2_count}")
        print(f"H3 headings: {seo_analysis.h3_count}")
        print(f"FAQ items: {seo_analysis.faq_count}")
        print(f"Summary section detected: {seo_analysis.has_summary}")
    print(f"Rakuten products: {len(products)}")
    print(f"Product prompt ready: {bool(product_result and product_result.prompt_text)}")
    print(f"Rakuten connected: {not rakuten_error}")
    if rakuten_error:
        print(f"Rakuten error: {rakuten_error}")
    print(f"Gemini connected: {not gemini_error}")
    if gemini_error:
        print(f"Gemini error: {gemini_error}")
    print(f"WordPress connected: {not wordpress_error}")
    if wordpress_error:
        print(f"WordPress error: {wordpress_error}")


if __name__ == "__main__":
    main()
