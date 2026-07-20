"""Entry point for the affiliate article generation system."""

import logging

import requests

from config.settings import PROJECT_ROOT, load_settings
from config.site_config import load_site_config
from google.genai import errors
from providers.gemini_provider import GeminiApiError, GeminiProvider
from providers.rakuten_provider import RakutenApiError, RakutenProvider
from providers.wordpress_provider import WordPressApiError, WordPressProvider
from services.article_consistency_service import (
    ArticleConsistencyError,
    ArticleConsistencyService,
)
from services.article_generator import ArticleGenerator, GeneratedArticle
from services.internal_link_service import InternalLinkService
from services.markdown_service import MarkdownService
from services.article_product_block_builder import (
    ProductBlocksError,
    ensure_affiliate_blocks_for_article,
)
from services.product_ranking_service import (
    ThemeProductSet,
    fetch_theme_product_set,
    format_problem_reference_products,
    format_product_article_prompt,
    format_product_names_list,
    format_ranking_article_prompt,
    save_theme_product_set,
    theme_product_set_path,
)
from services.prompt_manager import PromptManager
from services.seo_service import SeoService, replace_seo_slug
from services.site_manager import ArticleHistoryRecord, SiteManager
from services.theme_path_service import (
    article_slug,
    resolve_theme_slug,
    to_project_relative_path,
)
from services.wordpress_post_service import WordPressPostService
from utils.logger import setup_logging


logger = logging.getLogger(__name__)


def _replace_article_content(article: GeneratedArticle, content: str) -> GeneratedArticle:
    """Return a copy of a generated article with updated Markdown content."""
    return GeneratedArticle(
        theme=article.theme,
        article_type=article.article_type,
        content=content,
    )


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
    # InternalLinkServiceは、3記事のslugを使って関連記事リンクを追加する担当。
    internal_link_service = InternalLinkService()
    # ArticleConsistencyServiceは、3記事間の矛盾がないかGeminiで確認する担当。
    article_consistency_service = ArticleConsistencyService(
        prompt_manager=prompt_manager,
        gemini_provider=gemini_provider,
    )
    # MarkdownServiceは、生成済み記事を人が確認できる.mdファイルとして保存する担当。
    markdown_service = MarkdownService()
    # WordPressProviderはWordPress REST APIとの通信だけを担当する。
    # STEP08では安全のため投稿はせず、認証付きで接続できるかだけ確認する。
    wordpress_provider = WordPressProvider(
        site_url=settings.wordpress_url,
        username=settings.wordpress_username,
        app_password=settings.wordpress_app_password,
    )
    # WordPressPostServiceは、生成済み記事をWordPressの下書きへ登録する担当。
    wordpress_post_service = WordPressPostService(wordpress_provider)

    # 未処理テーマがある場合だけ、商品取得から記事生成までの確認処理を行う。
    wordpress_error = ""
    wordpress_post_result = None
    consistency_result = None
    consistency_error = ""
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
        product_set: ThemeProductSet | None = None
        try:
            product_set = fetch_theme_product_set(
                rakuten_provider,
                theme=next_theme,
                keyword=next_theme,
                hits=10,
            )
            save_theme_product_set(
                theme_product_set_path(site_config.output_dir, next_theme),
                product_set,
            )
            products = product_set.all_products
        except (RakutenApiError, ValueError) as error:
            logger.error("Rakuten product set build failed: %s", error)
            products = []
            product_set = None
            rakuten_error = str(error)

        try:
            if product_set is None:
                raise GeminiApiError(
                    "Cannot generate articles without at least 5 Rakuten products."
                )

            problem_prompt_text = format_problem_reference_products(product_set)
            product_prompt_text = format_product_article_prompt(product_set)
            ranking_prompt_text = format_ranking_article_prompt(product_set)
            product_order_text = format_product_names_list(product_set.product_display_order)
            ranking_order_text = format_product_names_list(product_set.ranking_top5)

            problem_article = article_generator.generate_problem_article(
                theme=next_theme,
                category=site_manager.get_default_category(),
                tags=site_manager.get_default_tags(),
                products=problem_prompt_text,
            )

            product_article = article_generator.generate_product_article(
                theme=next_theme,
                category=site_manager.get_default_category(),
                tags=site_manager.get_default_tags(),
                products=product_prompt_text,
                product_order=product_order_text,
            )
            product_body, product_set = ensure_affiliate_blocks_for_article(
                product_article.content,
                product_set,
                "product",
                output_dir=site_config.output_dir,
                rakuten_provider=rakuten_provider,
            )
            product_article = _replace_article_content(product_article, product_body)

            ranking_article = article_generator.generate_ranking_article(
                theme=next_theme,
                category=site_manager.get_default_category(),
                tags=site_manager.get_default_tags(),
                products=ranking_prompt_text,
                ranking_order=ranking_order_text,
            )
            ranking_body, product_set = ensure_affiliate_blocks_for_article(
                ranking_article.content,
                product_set,
                "ranking",
                output_dir=site_config.output_dir,
                rakuten_provider=rakuten_provider,
            )
            ranking_article = _replace_article_content(ranking_article, ranking_body)

            problem_seo_analysis = seo_service.analyze_article(problem_article.content)
            product_seo_analysis = seo_service.analyze_article(product_article.content)
            ranking_seo_analysis = seo_service.analyze_article(ranking_article.content)

            theme_slug = resolve_theme_slug(next_theme, site_config.site_dir)
            problem_seo_analysis = replace_seo_slug(
                problem_seo_analysis,
                article_slug("problem", theme_slug),
            )
            product_seo_analysis = replace_seo_slug(
                product_seo_analysis,
                article_slug("product", theme_slug),
            )
            ranking_seo_analysis = replace_seo_slug(
                ranking_seo_analysis,
                article_slug("ranking", theme_slug),
            )

            consistency_result = article_consistency_service.require_consistent_article_set(
                theme=next_theme,
                problem_article=problem_article,
                product_article=product_article,
                ranking_article=ranking_article,
                products=product_prompt_text,
            )

            # STEP14では、3記事が互いに行き来できるよう関連記事リンクを追加する。
            linked_articles = internal_link_service.apply_links(
                problem_article=problem_article,
                problem_seo=problem_seo_analysis,
                product_article=product_article,
                product_seo=product_seo_analysis,
                ranking_article=ranking_article,
                ranking_seo=ranking_seo_analysis,
            )
            problem_article = linked_articles.problem_article
            product_article = linked_articles.product_article
            ranking_article = linked_articles.ranking_article

            # STEP15では、内部リンク適用後の3記事をMarkdownファイルとして保存する。
            markdown_result = markdown_service.save_article_set(
                articles=linked_articles,
                problem_seo=problem_seo_analysis,
                product_seo=product_seo_analysis,
                ranking_seo=ranking_seo_analysis,
                output_dir=site_config.output_dir,
                site_dir=site_config.site_dir,
            )

            # STEP16では、WordPress接続が成功している場合だけ下書き投稿を作成する。
            # status=draftなので公開はされず、管理画面で内容確認できる状態になる。
            if not wordpress_error:
                try:
                    wordpress_post_result = wordpress_post_service.create_draft_post_set(
                        articles=linked_articles,
                        problem_seo=problem_seo_analysis,
                        product_seo=product_seo_analysis,
                        ranking_seo=ranking_seo_analysis,
                        products=products,
                    )
                except (WordPressApiError, requests.RequestException) as error:
                    logger.error("WordPress draft posting failed: %s", error)
                    wordpress_post_result = None
                    wordpress_error = str(error)

            if markdown_result is not None and markdown_result.is_ready:
                site_manager.record_theme_article_set(
                    theme=next_theme,
                    records=[
                        ArticleHistoryRecord(
                            article_type="problem",
                            title=problem_seo_analysis.seo_title,
                            slug=problem_seo_analysis.slug,
                            markdown_path=to_project_relative_path(
                                markdown_result.problem.path
                            ),
                            wordpress_post_id=(
                                wordpress_post_result.problem.post_id
                                if wordpress_post_result
                                else None
                            ),
                        ),
                        ArticleHistoryRecord(
                            article_type="product",
                            title=product_seo_analysis.seo_title,
                            slug=product_seo_analysis.slug,
                            markdown_path=to_project_relative_path(
                                markdown_result.product.path
                            ),
                            wordpress_post_id=(
                                wordpress_post_result.product.post_id
                                if wordpress_post_result
                                else None
                            ),
                        ),
                        ArticleHistoryRecord(
                            article_type="ranking",
                            title=ranking_seo_analysis.seo_title,
                            slug=ranking_seo_analysis.slug,
                            markdown_path=to_project_relative_path(
                                markdown_result.ranking.path
                            ),
                            wordpress_post_id=(
                                wordpress_post_result.ranking.post_id
                                if wordpress_post_result
                                else None
                            ),
                        ),
                    ],
                )
                logger.info("History saved for theme: %s", next_theme)
        except ArticleConsistencyError as error:
            logger.error("Article consistency check failed: %s", error)
            consistency_result = error.result
            consistency_error = str(error)
            problem_article = None
            product_article = None
            ranking_article = None
            linked_articles = None
            markdown_result = None
            wordpress_post_result = None
            gemini_error = consistency_error
            problem_seo_analysis = None
            product_seo_analysis = None
            ranking_seo_analysis = None
        except ProductBlocksError as error:
            logger.error("Affiliate product block validation failed: %s", error)
            problem_article = None
            product_article = None
            ranking_article = None
            linked_articles = None
            markdown_result = None
            wordpress_post_result = None
            gemini_error = str(error)
            problem_seo_analysis = None
            product_seo_analysis = None
            ranking_seo_analysis = None
        except (GeminiApiError, errors.APIError) as error:
            logger.error("Gemini article generation failed: %s", error)
            # Gemini側で失敗した場合も、原因をターミナルに表示するため文字列で保持する。
            problem_article = None
            product_article = None
            ranking_article = None
            linked_articles = None
            markdown_result = None
            wordpress_post_result = None
            gemini_error = str(error)
            problem_seo_analysis = None
            product_seo_analysis = None
            ranking_seo_analysis = None
    else:
        # すべてのテーマが処理済みなら、API通信は行わずに結果表示だけ行う。
        products = []
        product_set = None
        rakuten_error = ""
        gemini_error = ""
        problem_article = None
        product_article = None
        ranking_article = None
        linked_articles = None
        markdown_result = None
        wordpress_post_result = None
        problem_seo_analysis = None
        product_seo_analysis = None
        ranking_seo_analysis = None
        consistency_result = None
        consistency_error = ""

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
    if next_theme is not None and markdown_result is not None and markdown_result.is_ready:
        print(f"History saved for theme: {next_theme}")
    print(f"Prompt templates: {len(available_prompts)}")
    print(f"Problem article generated: {bool(problem_article and problem_article.is_generated)}")
    if problem_article is not None:
        print(f"Problem article type: {problem_article.article_type}")
        print(f"Problem article characters: {problem_article.character_count}")
    print(f"Product article generated: {bool(product_article and product_article.is_generated)}")
    if product_article is not None:
        print(f"Product article type: {product_article.article_type}")
        print(f"Product article characters: {product_article.character_count}")
    print(f"Ranking article generated: {bool(ranking_article and ranking_article.is_generated)}")
    if ranking_article is not None:
        print(f"Ranking article type: {ranking_article.article_type}")
        print(f"Ranking article characters: {ranking_article.character_count}")
    print(f"Problem SEO ready: {bool(problem_seo_analysis and problem_seo_analysis.is_ready)}")
    if problem_seo_analysis is not None:
        print(f"Problem SEO title detected: {bool(problem_seo_analysis.seo_title)}")
        print(
            "Problem meta description detected: "
            f"{bool(problem_seo_analysis.meta_description)}"
        )
        print(f"Problem slug detected: {bool(problem_seo_analysis.slug)}")
        print(f"Problem H2 headings: {problem_seo_analysis.h2_count}")
        print(f"Problem H3 headings: {problem_seo_analysis.h3_count}")
        print(f"Problem FAQ items: {problem_seo_analysis.faq_count}")
        print(f"Problem summary section detected: {problem_seo_analysis.has_summary}")
    print(f"Product SEO ready: {bool(product_seo_analysis and product_seo_analysis.is_ready)}")
    if product_seo_analysis is not None:
        print(f"Product SEO title detected: {bool(product_seo_analysis.seo_title)}")
        print(
            "Product meta description detected: "
            f"{bool(product_seo_analysis.meta_description)}"
        )
        print(f"Product slug detected: {bool(product_seo_analysis.slug)}")
        print(f"Product H2 headings: {product_seo_analysis.h2_count}")
        print(f"Product H3 headings: {product_seo_analysis.h3_count}")
        print(f"Product FAQ items: {product_seo_analysis.faq_count}")
        print(f"Product summary section detected: {product_seo_analysis.has_summary}")
    print(f"Ranking SEO ready: {bool(ranking_seo_analysis and ranking_seo_analysis.is_ready)}")
    if ranking_seo_analysis is not None:
        print(f"Ranking SEO title detected: {bool(ranking_seo_analysis.seo_title)}")
        print(
            "Ranking meta description detected: "
            f"{bool(ranking_seo_analysis.meta_description)}"
        )
        print(f"Ranking slug detected: {bool(ranking_seo_analysis.slug)}")
        print(f"Ranking H2 headings: {ranking_seo_analysis.h2_count}")
        print(f"Ranking H3 headings: {ranking_seo_analysis.h3_count}")
        print(f"Ranking FAQ items: {ranking_seo_analysis.faq_count}")
        print(f"Ranking summary section detected: {ranking_seo_analysis.has_summary}")
    print(
        "Article consistency passed: "
        f"{bool(consistency_result and consistency_result.is_consistent)}"
    )
    if consistency_result is not None:
        print(f"Article consistency summary: {consistency_result.summary}")
        print(f"Article consistency issues: {len(consistency_result.issues)}")
        for issue in consistency_result.issues:
            articles = ", ".join(issue.affected_articles) or "n/a"
            print(f"  - [{issue.severity}] {issue.category} ({articles}): {issue.description}")
    if consistency_error:
        print(f"Article consistency error: {consistency_error}")
    print(f"Internal links ready: {bool(linked_articles and linked_articles.is_ready)}")
    if linked_articles is not None:
        print(f"Internal links: {linked_articles.link_count}")
    print(f"Markdown saved: {bool(markdown_result and markdown_result.is_ready)}")
    if markdown_result is not None:
        print(f"Markdown files: {markdown_result.count}")
        print(f"Problem markdown: {markdown_result.problem.path}")
        print(f"Product markdown: {markdown_result.product.path}")
        print(f"Ranking markdown: {markdown_result.ranking.path}")
    print(
        "WordPress drafts created: "
        f"{bool(wordpress_post_result and wordpress_post_result.is_ready)}"
    )
    if wordpress_post_result is not None:
        print(f"WordPress draft posts: {wordpress_post_result.count}")
        print(f"Problem WordPress post ID: {wordpress_post_result.problem.post_id}")
        print(f"Product WordPress post ID: {wordpress_post_result.product.post_id}")
        print(f"Ranking WordPress post ID: {wordpress_post_result.ranking.post_id}")
    print(f"Rakuten products: {len(products)}")
    print(f"Theme product set ready: {bool(product_set)}")
    if product_set is not None:
        print(f"Product display order: {len(product_set.product_display_order)}")
        print(f"Ranking top5: {len(product_set.ranking_top5)}")
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
