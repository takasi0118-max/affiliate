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
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="You are a Japanese SEO affiliate article writer.",
                temperature=0.7,
            ),
        )

        if not response.text:
            raise GeminiApiError("Gemini response did not contain article text.")

        return response.text.strip()
