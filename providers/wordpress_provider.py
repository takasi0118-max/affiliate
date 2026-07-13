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
