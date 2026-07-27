"""Rakuten Ichiba API provider."""

from dataclasses import dataclass
from typing import Any
import logging
from urllib.parse import quote, urlencode

import requests

from utils.retry import retry


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RakutenProduct:
    """Product information returned from Rakuten Ichiba API."""

    # 記事生成に使う最低限の商品情報だけをここにまとめる。
    # APIレスポンスをそのまま使うより、必要な項目名に整理した方が後続処理が読みやすい。
    name: str
    price: int
    url: str
    image_url: str | None
    review_average: float | None
    review_count: int | None


class RakutenApiError(Exception):
    """Raised when Rakuten API returns an application-level error."""


class RakutenProvider:
    """Client for Rakuten Ichiba item search API."""

    # 楽天市場の商品検索APIのURL。商品名や価格などをキーワード検索できる。
    API_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
    # レビュー件数の多い順。楽天仕様上、sort は URL エンコードが必要。
    SORT_REVIEW_COUNT_DESC = "-reviewCount"

    def __init__(self, application_id: str, access_key: str, affiliate_id: str) -> None:
        """Initialize the provider with Rakuten credentials."""
        # 認証情報は直接コードに書かず、.env -> Settings -> main.py経由で受け取る。
        self.application_id = application_id
        self.access_key = access_key
        self.affiliate_id = affiliate_id

    @retry(
        max_attempts=3,
        delay_seconds=1.0,
        exceptions=(requests.RequestException,),
        logger=logger,
    )
    def search_items(
        self,
        keyword: str,
        hits: int = 5,
        *,
        sort: str | None = None,
        page: int = 1,
        has_review_flag: int = 1,
    ) -> list[RakutenProduct]:
        """Search Rakuten Ichiba items by keyword."""
        # 楽天APIへ送る検索条件。認証情報は.envから読み込んだ値を使う。
        # デフォルトはレビュー件数降順。hasReviewFlag=1 でレビューあり商品に限定する。
        sort_value = sort or self.SORT_REVIEW_COUNT_DESC
        params = {
            "applicationId": self.application_id,
            "accessKey": self.access_key,
            "affiliateId": self.affiliate_id,
            "keyword": keyword,
            "hits": min(max(hits, 1), 30),
            "page": page,
            "hasReviewFlag": has_review_flag,
            "format": "json",
            "formatVersion": 2,
        }
        # sort だけ先にエンコードし、二重エンコードを避けるため URL に直接付与する。
        query = urlencode(params, safe="")
        encoded_sort = quote(sort_value, safe="")
        request_url = f"{self.API_URL}?{query}&sort={encoded_sort}"
        response = requests.get(request_url, timeout=15)
        self._raise_for_api_error(response)

        # 楽天APIのJSONレスポンスからItems配列だけを取り出す。
        data = response.json()
        items = data.get("Items", [])
        if not isinstance(items, list):
            raise ValueError("Rakuten API response does not contain an item list.")

        # 取得した商品を1件ずつRakutenProductへ変換し、件数降順をクライアント側でも保証する。
        products = [self._parse_product(item) for item in items]
        products.sort(
            key=lambda product: (
                -(product.review_count or 0),
                -(product.review_average or 0.0),
                product.name,
            )
        )
        return products

    @staticmethod
    def _raise_for_api_error(response: requests.Response) -> None:
        """Raise sanitized errors without exposing API credentials."""
        # 正常系はそのまま呼び出し元へ戻し、400以上だけ例外へ変換する。
        if response.status_code < 400:
            return

        message = _extract_error_message(response)
        # 5xxは一時的なサーバー障害の可能性があるためrequests系例外として扱う。
        if response.status_code >= 500:
            raise requests.HTTPError(
                f"Rakuten API server error {response.status_code}: {message}",
                response=response,
            )

        # 400番台はID間違い・パラメータ不足など、こちらの設定や入力が原因のことが多い。
        raise RakutenApiError(
            f"Rakuten API request error {response.status_code}: {message}"
        )

    @staticmethod
    def _parse_product(item: dict[str, Any]) -> RakutenProduct:
        """Convert a Rakuten API item into a RakutenProduct."""
        # APIレスポンスのキー名を、アプリ内で扱いやすい商品データへ詰め替える。
        image_urls = item.get("mediumImageUrls") or []
        image_url = None
        if image_urls and isinstance(image_urls[0], str):
            image_url = image_urls[0]

        return RakutenProduct(
            name=str(item.get("itemName", "")),
            price=int(item.get("itemPrice", 0)),
            url=str(item.get("affiliateUrl") or item.get("itemUrl") or ""),
            image_url=image_url,
            review_average=_to_optional_float(item.get("reviewAverage")),
            review_count=_to_optional_int(item.get("reviewCount")),
        )


def _to_optional_float(value: Any) -> float | None:
    """Convert a value to float when possible."""
    # レビュー平均のように、値が無い場合もある項目はNoneとして扱う。
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_optional_int(value: Any) -> int | None:
    """Convert a value to int when possible."""
    # レビュー件数のように、値が無い場合もある項目はNoneとして扱う。
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_error_message(response: requests.Response) -> str:
    """Extract a concise error message from a Rakuten API response."""
    # 楽天APIのエラー本文はJSONの場合が多いので、まずJSONとして読んでみる。
    try:
        data = response.json()
    except ValueError:
        return response.text[:200] or "No error detail returned."

    # よく使われるエラー項目名を順番に見て、見つかったものを表示用メッセージにする。
    for key in ("error_description", "error", "message"):
        value = data.get(key)
        if value:
            return str(value)

    return "No error detail returned."
