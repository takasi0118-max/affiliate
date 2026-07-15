"""WordPress REST API provider for draft posting."""

from typing import Any
import json

import requests


class WordPressApiError(Exception):
    """Raised when WordPress returns an application-level error."""


class WordPressProvider:
    """Client for WordPress REST API operations."""

    def __init__(self, site_url: str, username: str, app_password: str) -> None:
        """Initialize the provider with WordPress credentials."""
        # site_urlは末尾の/があってもなくても扱えるよう、ここで形をそろえる。
        self.site_url = site_url.rstrip("/")
        self.username = username
        self.app_password = app_password

    def test_connection(self) -> bool:
        """Check whether the configured WordPress credentials are valid."""
        # /users/me は、Application Password認証が成功しているか確認しやすいエンドポイント。
        response = self._request("GET", "/wp-json/wp/v2/users/me")
        return response.status_code == 200

    def create_draft_post(
        self,
        title: str,
        content: str,
        slug: str = "",
        excerpt: str = "",
        categories: list[int] | None = None,
        tags: list[int] | None = None,
    ) -> int:
        """Create a WordPress draft post and return its post ID."""
        # status=draftにすることで、公開せずWordPress管理画面の下書きに保存する。
        payload: dict[str, Any] = {
            "title": title,
            "content": content,
            "status": "draft",
        }
        if slug:
            payload["slug"] = slug
        if excerpt:
            payload["excerpt"] = excerpt
        if categories:
            payload["categories"] = categories
        if tags:
            payload["tags"] = tags

        response = self._request("POST", "/wp-json/wp/v2/posts", json=payload)
        data = response.json()
        post_id = data.get("id")
        if not isinstance(post_id, int):
            raise WordPressApiError("WordPress response did not contain a post ID.")
        return post_id

    def update_post(
        self,
        post_id: int,
        content: str,
        title: str = "",
        slug: str = "",
        excerpt: str = "",
    ) -> int:
        """Update an existing WordPress post and return its post ID."""
        # 既存の下書きをHTML版へ差し替える時に使う。statusは変更しないので公開状態はそのまま。
        payload: dict[str, Any] = {
            "content": content,
        }
        if title:
            payload["title"] = title
        if slug:
            payload["slug"] = slug
        if excerpt:
            payload["excerpt"] = excerpt

        response = self._request(
            "POST",
            f"/wp-json/wp/v2/posts/{post_id}",
            json=payload,
        )
        data = response.json()
        updated_post_id = data.get("id")
        if not isinstance(updated_post_id, int):
            raise WordPressApiError("WordPress response did not contain a post ID.")
        return updated_post_id

    def get_post(self, post_id: int) -> dict[str, Any]:
        """Return one WordPress post response as a dictionary."""
        # 更新後の確認用。title/status/linkなど、WordPress側の状態を読む。
        response = self._request("GET", f"/wp-json/wp/v2/posts/{post_id}")
        data = response.json()
        if not isinstance(data, dict):
            raise WordPressApiError("WordPress response did not contain post data.")
        return data

    def create_draft_page(
        self,
        title: str,
        content: str,
        slug: str = "",
        excerpt: str = "",
    ) -> int:
        """Create a WordPress draft page and return its page ID."""
        # 固定ページは記事一覧には混ざらず、案内ページなどに使いやすい。
        payload: dict[str, Any] = {
            "title": title,
            "content": content,
            "status": "draft",
        }
        if slug:
            payload["slug"] = slug
        if excerpt:
            payload["excerpt"] = excerpt

        response = self._request("POST", "/wp-json/wp/v2/pages", json=payload)
        data = response.json()
        page_id = data.get("id")
        if not isinstance(page_id, int):
            raise WordPressApiError("WordPress response did not contain a page ID.")
        return page_id

    def get_page(self, page_id: int) -> dict[str, Any]:
        """Return one WordPress page response as a dictionary."""
        response = self._request("GET", f"/wp-json/wp/v2/pages/{page_id}")
        data = response.json()
        if not isinstance(data, dict):
            raise WordPressApiError("WordPress response did not contain page data.")
        return data

    def update_page(
        self,
        page_id: int,
        content: str,
        title: str = "",
        slug: str = "",
        excerpt: str = "",
    ) -> int:
        """Update an existing WordPress page and return its page ID."""
        # 固定ページの下書き内容を差し替える時に使う。statusは変えない。
        payload: dict[str, Any] = {
            "content": content,
        }
        if title:
            payload["title"] = title
        if slug:
            payload["slug"] = slug
        if excerpt:
            payload["excerpt"] = excerpt

        response = self._request(
            "POST",
            f"/wp-json/wp/v2/pages/{page_id}",
            json=payload,
        )
        data = response.json()
        updated_page_id = data.get("id")
        if not isinstance(updated_page_id, int):
            raise WordPressApiError("WordPress response did not contain a page ID.")
        return updated_page_id

    def find_pages_by_slug(self, slug: str) -> list[dict[str, Any]]:
        """Return WordPress pages that match a slug."""
        # 同じ固定ページを何度も作らないよう、作成前にslugで既存ページを確認する。
        response = self._request(
            "GET",
            f"/wp-json/wp/v2/pages?slug={slug}&status=any",
        )
        data = response.json()
        if not isinstance(data, list):
            raise WordPressApiError("WordPress response did not contain page data.")
        return [item for item in data if isinstance(item, dict)]

    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> requests.Response:
        """Send an authenticated request to WordPress."""
        # Application PasswordはBasic認証として送る。値はログやエラー文には出さない。
        response = requests.request(
            method=method,
            url=f"{self.site_url}{path}",
            auth=(self.username, self.app_password),
            json=json,
            timeout=15,
        )
        self._raise_for_api_error(response)
        return response

    @staticmethod
    def _raise_for_api_error(response: requests.Response) -> None:
        """Raise sanitized errors without exposing WordPress credentials."""
        # 200番台は成功なので、そのまま呼び出し元へ返す。
        if response.status_code < 400:
            return

        message = _extract_error_message(response)
        raise WordPressApiError(
            f"WordPress API request error {response.status_code}: {message}"
        )


def _extract_error_message(response: requests.Response) -> str:
    """Extract a concise error message from a WordPress API response."""
    # WordPress REST APIのエラーはJSONでcode/messageを返すことが多い。
    try:
        data = json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return response.text[:200] or "No error detail returned."

    code = data.get("code")
    if code:
        # Windows端末では日本語messageが文字化けすることがあるため、英数字のcodeを優先する。
        return str(code)

    message = data.get("message")
    if message:
        return str(message)

    return "No error detail returned."
