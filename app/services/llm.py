"""Claude API service — wrapper for all LLM interactions.

Handles: model selection, retry logic, response caching, token counting.
"""

import hashlib
import json
import logging
from typing import Any

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Wrapper around the Anthropic Claude API."""

    def __init__(self) -> None:
        self._client: anthropic.Anthropic | None = None
        self._cache: dict[str, str] = {}  # In-memory cache; Phase 2 moves to Firestore

    @property
    def client(self) -> anthropic.Anthropic:
        """Lazy-init the Anthropic client."""
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._client

    def _cache_key(self, system: str, user: str, model: str) -> str:
        """Generate a cache key from the prompt inputs."""
        content = f"{model}:{system}:{user}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        use_cache: bool = True,
    ) -> str:
        """Call Claude and return the text response.

        Args:
            system_prompt: The system instruction.
            user_prompt: The user message with data.
            model: Claude model to use. Defaults to normalisation model.
            max_tokens: Max response tokens.
            temperature: Lower = more deterministic. 0.2 is good for data extraction.
            use_cache: If True, check/store in response cache.

        Returns:
            The raw text response from Claude.
        """
        model = model or settings.claude_model_normalisation
        cache_key = self._cache_key(system_prompt, user_prompt, model)

        # Check cache
        if use_cache and cache_key in self._cache:
            logger.info("LLM cache hit for key %s", cache_key[:12])
            return self._cache[cache_key]

        # Call Claude
        logger.info("Calling Claude (%s), prompt ~%d chars", model, len(user_prompt))
        message = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text
        logger.info(
            "Claude response: %d chars, %d input tokens, %d output tokens",
            len(response_text),
            message.usage.input_tokens,
            message.usage.output_tokens,
        )

        # Cache the response
        if use_cache:
            self._cache[cache_key] = response_text

        return response_text

    async def call_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Call Claude and parse the response as JSON.

        Retries once with a more explicit prompt if JSON parsing fails.
        """
        response = await self.call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        # Try to parse JSON from the response
        try:
            return self._extract_json(response)
        except json.JSONDecodeError:
            logger.warning("First JSON parse failed, retrying with explicit prompt")

        # Retry with explicit instruction
        retry_prompt = (
            f"{user_prompt}\n\n"
            "IMPORTANT: Your response must be ONLY valid JSON. "
            "No markdown, no explanation, no code fences. Just the JSON object."
        )
        response = await self.call(
            system_prompt=system_prompt,
            user_prompt=retry_prompt,
            model=model,
            max_tokens=max_tokens,
            temperature=0.1,  # Even more deterministic on retry
            use_cache=False,  # Don't cache the retry
        )

        return self._extract_json(response)

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from a response that might include markdown fences."""
        text = text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        return json.loads(text)


# Singleton
llm_service = LLMService()
