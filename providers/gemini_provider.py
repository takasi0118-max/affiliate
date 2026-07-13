"""Gemini API provider for article generation."""

import logging

from google import genai
from google.genai import errors, types

from utils.retry import retry


logger = logging.getLogger(__name__)


class GeminiApiError(Exception):
    """Raised when Gemini returns an unusable response."""


class GeminiProvider:
    """Client for generating article text with Gemini."""

    def __init__(self, api_key: str, model: str) -> None:
        """Initialize the Gemini client."""
        # genai.ClientはGemini APIへ通信するための公式クライアント。
        # api_keyには.envのGEMINI_API_KEY、modelにはGEMINI_MODELを渡す。
        self.client = genai.Client(api_key=api_key)
        self.model = model

    @retry(
        max_attempts=2,
        delay_seconds=2.0,
        exceptions=(errors.APIError,),
        logger=logger,
    )
    def generate_text(self, prompt: str) -> str:
        """Generate Markdown article text from a prompt."""
        # PromptManagerで組み立てた記事指示をGeminiへ送り、Markdown本文を生成する。
        # contentsがユーザーからの指示文、configが生成方法の設定。
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                # system_instructionは、Geminiに「どんな役割で答えるか」を伝える固定指示。
                system_instruction="You are a Japanese SEO affiliate article writer.",
                # temperatureは文章のゆらぎ。0に近いほど無難、1に近いほど表現が広がる。
                temperature=0.7,
            ),
        )

        # 空レスポンスを成功扱いにしないよう、本文があることを明示的に確認する。
        if not response.text:
            raise GeminiApiError("Gemini response did not contain article text.")

        # 前後の余分な空白や改行を取り除いた本文だけを呼び出し元へ返す。
        return response.text.strip()
