# -*- coding: utf-8 -*-
"""
===================================
Unit tests for SearchService provider-selection logic
===================================

Validates that NEWS_PROVIDER / news_provider behaves as documented:
- "auto": priority-based fallback (Bocha → Tavily → Brave → SerpAPI),
  only ONE provider is called per query (no duplicate calls).
- Named provider: only that provider is used; falls back to auto with a
  warning when the named provider is not configured or unavailable.
"""

import unittest
from unittest.mock import MagicMock

from src.search_service import SearchResponse, SearchResult, SearchService


def _make_response(provider_name: str, success: bool = True) -> SearchResponse:
    """Build a minimal SearchResponse for testing."""
    results = (
        [SearchResult(title="t", snippet="s", url="http://example.com", source="ex")]
        if success
        else []
    )
    return SearchResponse(
        query="test",
        results=results,
        provider=provider_name,
        success=success,
        error_message=None if success else "mock failure",
    )


def _make_mock_provider(name: str, success: bool = True) -> MagicMock:
    """Create a fully-mocked provider."""
    mock = MagicMock()
    mock.name = name
    mock.is_available = True
    mock.search = MagicMock(return_value=_make_response(name, success=success))
    return mock


class ProviderSelectionAutoModeTest(unittest.TestCase):
    """Tests for news_provider='auto' (default) strategy."""

    def _make_service_with_mocked_providers(self, tavily_success=True, serpapi_success=True):
        """Create a SearchService with two mock providers."""
        service = SearchService(news_provider="auto")
        service._providers = [
            _make_mock_provider("Tavily", success=tavily_success),
            _make_mock_provider("SerpAPI", success=serpapi_success),
        ]
        return service

    def test_auto_uses_first_available_provider(self):
        """auto mode: first provider (Tavily) is used when it succeeds."""
        service = self._make_service_with_mocked_providers(tavily_success=True)
        response = service.search_stock_news("600519", "贵州茅台")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Tavily")

        # Verify SerpAPI was NOT called (no duplicate query)
        serpapi_mock = service._providers[1]
        serpapi_mock.search.assert_not_called()

    def test_auto_falls_back_when_first_provider_fails(self):
        """auto mode: falls back to SerpAPI when Tavily returns no results."""
        service = self._make_service_with_mocked_providers(tavily_success=False, serpapi_success=True)
        response = service.search_stock_news("600519", "贵州茅台")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "SerpAPI")

        # Verify Tavily was tried first
        tavily_mock = service._providers[0]
        tavily_mock.search.assert_called_once()

    def test_auto_returns_failure_when_all_providers_fail(self):
        """auto mode: returns failure response when all providers fail."""
        service = self._make_service_with_mocked_providers(tavily_success=False, serpapi_success=False)
        response = service.search_stock_news("600519", "贵州茅台")

        self.assertFalse(response.success)
        self.assertEqual(response.provider, "None")


class ProviderSelectionExplicitModeTest(unittest.TestCase):
    """Tests for explicit news_provider selection."""

    def _make_service(self, news_provider: str):
        """Create a SearchService with two mock providers and given news_provider."""
        service = SearchService(news_provider=news_provider)
        service._providers = [
            _make_mock_provider("Tavily", success=True),
            _make_mock_provider("SerpAPI", success=True),
        ]
        return service

    def test_explicit_provider_only_calls_named_provider(self):
        """Explicit 'tavily': only Tavily is called, SerpAPI is skipped."""
        service = self._make_service("tavily")
        response = service.search_stock_news("600519", "贵州茅台")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "Tavily")

        serpapi_mock = service._providers[1]
        serpapi_mock.search.assert_not_called()

    def test_explicit_provider_serpapi(self):
        """Explicit 'serpapi': only SerpAPI is called, Tavily is skipped."""
        service = self._make_service("serpapi")
        response = service.search_stock_news("600519", "贵州茅台")

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "SerpAPI")

        tavily_mock = service._providers[0]
        tavily_mock.search.assert_not_called()

    def test_explicit_provider_not_configured_falls_back_to_auto(self):
        """If named provider is not configured, fall back to auto mode."""
        # 'brave' is not present in the provider list, so auto fallback expected
        service = SearchService(news_provider="brave")
        service._providers = [_make_mock_provider("Tavily", success=True)]

        with self.assertLogs("src.search_service", level="WARNING") as cm:
            providers = service._get_providers_for_search()

        # Should fall back to all available providers
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].name, "Tavily")
        self.assertTrue(any("Falling back to auto mode" in msg for msg in cm.output))

    def test_get_providers_for_search_auto_returns_all(self):
        """_get_providers_for_search returns all available providers in auto mode."""
        service = SearchService(
            tavily_keys=["t-key"],
            serpapi_keys=["s-key"],
            news_provider="auto",
        )
        providers = service._get_providers_for_search()
        names = [p.name for p in providers]
        self.assertIn("Tavily", names)
        self.assertIn("SerpAPI", names)

    def test_get_providers_for_search_named_returns_single(self):
        """_get_providers_for_search returns only the named provider when set."""
        service = SearchService(
            tavily_keys=["t-key"],
            serpapi_keys=["s-key"],
            news_provider="serpapi",
        )
        providers = service._get_providers_for_search()
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].name, "SerpAPI")


class ConfigNewsProviderTest(unittest.TestCase):
    """Tests for NEWS_PROVIDER env var loading via Config."""

    def test_default_news_provider_is_auto(self):
        """Config.news_provider defaults to 'auto' when NEWS_PROVIDER is not set."""
        import os
        from src.config import Config

        Config.reset_instance()
        env_backup = os.environ.pop("NEWS_PROVIDER", None)
        try:
            config = Config._load_from_env()
            self.assertEqual(config.news_provider, "auto")
        finally:
            if env_backup is not None:
                os.environ["NEWS_PROVIDER"] = env_backup
            Config.reset_instance()

    def test_news_provider_loaded_from_env(self):
        """Config.news_provider reads NEWS_PROVIDER env var."""
        import os
        from src.config import Config

        Config.reset_instance()
        os.environ["NEWS_PROVIDER"] = "tavily"
        try:
            config = Config._load_from_env()
            self.assertEqual(config.news_provider, "tavily")
        finally:
            del os.environ["NEWS_PROVIDER"]
            Config.reset_instance()

    def test_validate_warns_on_unknown_provider(self):
        """validate() warns when NEWS_PROVIDER is an unrecognised value."""
        from src.config import Config

        config = Config(
            tavily_api_keys=["key"],
            news_provider="unknown_engine",
        )
        warnings = config.validate()
        self.assertTrue(
            any("NEWS_PROVIDER" in w and "不是有效值" in w for w in warnings),
            f"Expected validation warning for unknown provider, got: {warnings}",
        )

    def test_validate_warns_when_provider_key_missing(self):
        """validate() warns when NEWS_PROVIDER names a provider without a configured key."""
        from src.config import Config

        config = Config(
            tavily_api_keys=["key"],
            news_provider="bocha",  # bocha_api_keys is empty
        )
        warnings = config.validate()
        self.assertTrue(
            any("bocha" in w and "API Key 未配置" in w for w in warnings),
            f"Expected warning about missing bocha key, got: {warnings}",
        )


if __name__ == "__main__":
    unittest.main()

