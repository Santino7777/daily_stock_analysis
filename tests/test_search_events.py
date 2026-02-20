# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - search_stock_events 多维度搜索单元测试
===================================

验收标准：
1. 旧调用方式（显式 event_types）仍然正常运行，返回 SearchResponse。
2. event_types=None 时触发多维度搜索，结果聚合去重，至少覆盖 3 个维度。
3. search_stock_events_by_dimension() 返回 Dict[str, SearchResponse]，包含各维度结果。
4. format_events_report() 输出包含各维度标题和结果摘要的文本。
5. 无可用 provider 时，搜索方法应优雅降级，不抛出异常。
"""

import time
import unittest
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

from src.search_service import SearchResponse, SearchResult, SearchService


def _make_result(title: str, url: str = "", snippet: str = "摘要内容") -> SearchResult:
    """构造测试用 SearchResult。"""
    return SearchResult(
        title=title,
        snippet=snippet,
        url=url or f"https://example.com/{title}",
        source="example.com",
        published_date="2025-01-01",
    )


def _make_success_response(query: str, results: Optional[List[SearchResult]] = None) -> SearchResponse:
    """构造成功的 SearchResponse。"""
    return SearchResponse(
        query=query,
        results=results or [_make_result(f"结果: {query}")],
        provider="MockProvider",
        success=True,
    )


def _make_failure_response(query: str) -> SearchResponse:
    """构造失败的 SearchResponse。"""
    return SearchResponse(
        query=query,
        results=[],
        provider="MockProvider",
        success=False,
        error_message="mock failure",
    )


class TestSearchStockEventsBackwardCompat(unittest.TestCase):
    """旧调用方式（显式 event_types）的向后兼容测试。"""

    def _make_service_with_mock_provider(self) -> SearchService:
        """创建带有 mock provider 的 SearchService。"""
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        mock_provider = MagicMock()
        mock_provider.is_available = True
        mock_provider.name = "MockProvider"
        mock_provider.search.return_value = _make_success_response("贵州茅台 (年报预告 OR 减持公告)")
        svc._providers = [mock_provider]
        return svc

    def test_explicit_event_types_returns_search_response(self):
        """显式 event_types 时，返回 SearchResponse（向后兼容）。"""
        svc = self._make_service_with_mock_provider()
        result = svc.search_stock_events("600519", "贵州茅台", event_types=["年报预告", "减持公告"])

        self.assertIsInstance(result, SearchResponse)
        self.assertTrue(result.success)
        self.assertGreater(len(result.results), 0)

    def test_explicit_event_types_uses_or_query(self):
        """显式 event_types 时，应构造 OR 拼接的单查询。"""
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        mock_provider = MagicMock()
        mock_provider.is_available = True
        mock_provider.name = "MockProvider"
        mock_provider.search.return_value = _make_success_response("test query")
        svc._providers = [mock_provider]

        svc.search_stock_events("600519", "贵州茅台", event_types=["年报预告", "业绩快报"])

        # 验证调用了单次 search，query 包含 OR
        self.assertEqual(mock_provider.search.call_count, 1)
        called_query = mock_provider.search.call_args[0][0]
        self.assertIn("OR", called_query)
        self.assertIn("年报预告", called_query)
        self.assertIn("业绩快报", called_query)

    def test_all_providers_fail_returns_failure_response(self):
        """所有 provider 失败时，仍返回 SearchResponse（success=False），不抛出异常。"""
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        mock_provider = MagicMock()
        mock_provider.is_available = True
        mock_provider.name = "MockProvider"
        mock_provider.search.return_value = _make_failure_response("test")
        svc._providers = [mock_provider]

        result = svc.search_stock_events("600519", "贵州茅台", event_types=["年报预告"])
        self.assertIsInstance(result, SearchResponse)
        self.assertFalse(result.success)


class TestSearchStockEventsMultiDim(unittest.TestCase):
    """event_types=None 时的多维度搜索行为测试。"""

    def _make_service(self, per_call_results: int = 2) -> tuple:
        """
        返回 (svc, mock_provider)，provider.search 每次调用返回 per_call_results 条结果。
        结果 URL 含有调用序号以区分唯一性。
        """
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        mock_provider = MagicMock()
        mock_provider.is_available = True
        mock_provider.name = "MockProvider"

        call_counter = {"n": 0}

        def side_effect(query, max_results=5, **kwargs):
            n = call_counter["n"]
            call_counter["n"] += 1
            results = [_make_result(f"标题_{n}_{i}", url=f"https://example.com/{n}/{i}") for i in range(per_call_results)]
            return SearchResponse(query=query, results=results, provider="MockProvider", success=True)

        mock_provider.search.side_effect = side_effect
        svc._providers = [mock_provider]
        return svc, mock_provider

    def test_returns_search_response(self):
        """event_types=None 时仍返回 SearchResponse（向后兼容）。"""
        svc, _ = self._make_service()
        with patch("time.sleep"):
            result = svc.search_stock_events("600519", "贵州茅台")

        self.assertIsInstance(result, SearchResponse)

    def test_multi_dim_calls_multiple_searches(self):
        """event_types=None 时应执行多于 1 次的搜索调用（对应多个维度）。"""
        svc, mock_provider = self._make_service()
        with patch("time.sleep"):
            svc.search_stock_events("600519", "贵州茅台")

        self.assertGreaterEqual(mock_provider.search.call_count, 3, "至少应搜索 3 个维度")

    def test_results_are_deduplicated(self):
        """跨维度重复 URL 的结果应被去重。"""
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        mock_provider = MagicMock()
        mock_provider.is_available = True
        mock_provider.name = "MockProvider"
        # 所有维度返回相同 URL 的结果
        shared_result = _make_result("重复标题", url="https://same-url.com/article")
        mock_provider.search.return_value = _make_success_response("q", [shared_result])
        svc._providers = [mock_provider]

        with patch("time.sleep"):
            result = svc.search_stock_events("600519", "贵州茅台")

        # 相同 URL 只应出现一次
        urls = [r.url for r in result.results]
        self.assertEqual(len(urls), len(set(urls)), "结果中存在重复 URL")

    def test_foreign_stock_uses_english_dimensions(self):
        """美股/港股使用英文维度模板。"""
        svc, mock_provider = self._make_service()
        with patch("time.sleep"):
            svc.search_stock_events("AAPL", "Apple")

        # 英文维度的查询应包含英文关键词
        calls = [call[0][0] for call in mock_provider.search.call_args_list]
        self.assertTrue(any("earnings" in q or "insider" in q or "litigation" in q for q in calls))

    def test_no_provider_returns_failure(self):
        """无可用 provider 时返回 success=False 的 SearchResponse，不抛出异常。"""
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        svc._providers = []

        result = svc.search_stock_events("600519", "贵州茅台")
        self.assertIsInstance(result, SearchResponse)
        self.assertFalse(result.success)


class TestSearchStockEventsByDimension(unittest.TestCase):
    """search_stock_events_by_dimension() 专项测试。"""

    def _make_service(self) -> tuple:
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        mock_provider = MagicMock()
        mock_provider.is_available = True
        mock_provider.name = "MockProvider"
        call_counter = {"n": 0}

        def side_effect(query, max_results=5, **kwargs):
            n = call_counter["n"]
            call_counter["n"] += 1
            return SearchResponse(
                query=query,
                results=[_make_result(f"dim{n}_result", url=f"https://ex.com/{n}")],
                provider="MockProvider",
                success=True,
            )

        mock_provider.search.side_effect = side_effect
        svc._providers = [mock_provider]
        return svc, mock_provider

    def test_returns_dict_of_search_responses(self):
        """返回值为 Dict[str, SearchResponse]。"""
        svc, _ = self._make_service()
        with patch("time.sleep"):
            result = svc.search_stock_events_by_dimension("600519", "贵州茅台")

        self.assertIsInstance(result, dict)
        for key, val in result.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(val, SearchResponse)

    def test_returns_at_least_three_dimensions(self):
        """至少返回 3 个维度。"""
        svc, _ = self._make_service()
        with patch("time.sleep"):
            result = svc.search_stock_events_by_dimension("600519", "贵州茅台")

        self.assertGreaterEqual(len(result), 3, f"应至少返回 3 个维度，实际: {list(result.keys())}")

    def test_expected_dimension_names_cn(self):
        """A股应包含预期的中文维度名。"""
        svc, _ = self._make_service()
        with patch("time.sleep"):
            result = svc.search_stock_events_by_dimension("600519", "贵州茅台")

        expected = {"earnings", "insider", "risk"}
        self.assertTrue(expected.issubset(set(result.keys())), f"缺少预期维度，实际: {list(result.keys())}")

    def test_expected_dimension_names_en(self):
        """英文股票应包含预期的英文维度名。"""
        svc, _ = self._make_service()
        with patch("time.sleep"):
            result = svc.search_stock_events_by_dimension("AAPL", "Apple")

        expected = {"earnings", "insider", "risk"}
        self.assertTrue(expected.issubset(set(result.keys())), f"缺少预期维度，实际: {list(result.keys())}")

    def test_max_dims_limits_number_of_dimensions(self):
        """max_dims 参数应限制实际执行的维度数量。"""
        svc, mock_provider = self._make_service()
        with patch("time.sleep"):
            result = svc.search_stock_events_by_dimension("600519", "贵州茅台", max_dims=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(mock_provider.search.call_count, 2)

    def test_no_provider_returns_failure_dict(self):
        """无可用 provider 时，返回每个维度均 success=False 的字典，不抛出异常。"""
        svc = SearchService.__new__(SearchService)
        svc._cache = {}
        svc._cache_ttl = 600
        svc._providers = []

        result = svc.search_stock_events_by_dimension("600519", "贵州茅台")
        self.assertIsInstance(result, dict)
        self.assertGreater(len(result), 0)
        for val in result.values():
            self.assertFalse(val.success)

    def test_sleep_is_called_between_dimensions(self):
        """维度之间应调用 time.sleep。"""
        svc, _ = self._make_service()
        with patch("time.sleep") as mock_sleep:
            svc.search_stock_events_by_dimension("600519", "贵州茅台", sleep_between_dims=0.3)

        # N 个维度 => N-1 次 sleep
        self.assertGreater(mock_sleep.call_count, 0)


class TestFormatEventsReport(unittest.TestCase):
    """format_events_report() 格式化报告测试。"""

    def _make_service(self) -> SearchService:
        svc = SearchService.__new__(SearchService)
        svc._providers = []
        return svc

    def _build_dim_results(self) -> Dict[str, SearchResponse]:
        return {
            "earnings": _make_success_response(
                "贵州茅台 业绩",
                [_make_result("茅台Q3业绩预增30%", snippet="营收同比增长明显")],
            ),
            "insider": _make_success_response(
                "贵州茅台 减持",
                [_make_result("大股东减持200万股", snippet="持股比例下降")],
            ),
            "risk": _make_failure_response("贵州茅台 风险"),
            "regulatory": _make_success_response(
                "贵州茅台 监管",
                [_make_result("食品监管新规发布", snippet="行业合规要求提升")],
            ),
        }

    def test_returns_string(self):
        """format_events_report 应返回字符串。"""
        svc = self._make_service()
        report = svc.format_events_report(self._build_dim_results(), "贵州茅台")
        self.assertIsInstance(report, str)

    def test_report_contains_stock_name(self):
        """报告应包含股票名称。"""
        svc = self._make_service()
        report = svc.format_events_report(self._build_dim_results(), "贵州茅台")
        self.assertIn("贵州茅台", report)

    def test_report_contains_all_dimensions(self):
        """报告应覆盖所有传入的维度（通过描述标签或结果内容体现）。"""
        svc = self._make_service()
        dim_results = self._build_dim_results()
        report = svc.format_events_report(dim_results, "贵州茅台")
        # 业绩和内部人维度有成功结果，应出现在报告中
        self.assertIn("茅台Q3业绩预增30%", report, "earnings 维度结果标题应出现在报告中")
        self.assertIn("大股东减持200万股", report, "insider 维度结果标题应出现在报告中")
        self.assertIn("食品监管新规发布", report, "regulatory 维度结果标题应出现在报告中")

    def test_report_contains_article_titles(self):
        """报告应包含成功维度的文章标题。"""
        svc = self._make_service()
        report = svc.format_events_report(self._build_dim_results(), "贵州茅台")
        self.assertIn("茅台Q3业绩预增30%", report)
        self.assertIn("大股东减持200万股", report)

    def test_failed_dimension_shows_no_results_message(self):
        """失败的维度应显示未找到相关信息提示。"""
        svc = self._make_service()
        report = svc.format_events_report(self._build_dim_results(), "贵州茅台")
        self.assertIn("未找到相关信息", report)

    def test_empty_dim_results(self):
        """传入空字典时不应抛出异常，且应包含股票名称。"""
        svc = self._make_service()
        report = svc.format_events_report({}, "贵州茅台")
        self.assertIsInstance(report, str)
        self.assertIn("贵州茅台", report)


if __name__ == "__main__":
    unittest.main()
