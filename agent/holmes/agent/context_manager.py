"""Context manager for token usage tracking and /compact threshold detection."""

from __future__ import annotations


WARNING_THRESHOLD = 0.80  # 80% of max tokens


class ContextManager:
    """Tracks token usage and detects when /compact should be suggested.

    Args:
        max_tokens: Maximum context window size.
    """

    def __init__(self, max_tokens: int = 200_000) -> None:
        self._max_tokens = max_tokens
        self._used_tokens = 0

    @property
    def used_tokens(self) -> int:
        return self._used_tokens

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def usage_ratio(self) -> float:
        if self._max_tokens == 0:
            return 0.0
        return self._used_tokens / self._max_tokens

    @property
    def is_warning(self) -> bool:
        """True when usage exceeds 80% threshold."""
        return self.usage_ratio >= WARNING_THRESHOLD

    def update(self, total_tokens: int) -> None:
        """Update the running token count.

        Args:
            total_tokens: Cumulative tokens used in current session.
        """
        self._used_tokens = max(self._used_tokens, total_tokens)

    def reset(self) -> None:
        """Reset token count after a /compact operation."""
        self._used_tokens = 0
