# -*- coding: utf-8 -*-
"""
===================================
US stock ticker recognition and routing tests
===================================

Validates:
1. _is_us_code correctly identifies US tickers (including hyphen/dot class shares)
2. DataFetcherManager.get_daily_data routes US tickers to YfinanceFetcher first
3. YfinanceFetcher._convert_stock_code produces correct yfinance symbols
"""

import unittest
from unittest.mock import MagicMock, patch
import pandas as pd


class TestIsUsCode(unittest.TestCase):
    """Tests for the _is_us_code helper across all fetchers."""

    def _get_fn(self):
        from data_provider.akshare_fetcher import _is_us_code
        return _is_us_code

    # --- should be recognised as US tickers ---
    def test_simple_uppercase(self):
        fn = self._get_fn()
        for code in ("AAPL", "TSLA", "MSFT", "META", "BMNR", "CIFR", "AMD", "GOOGL"):
            with self.subTest(code=code):
                self.assertTrue(fn(code), f"{code} should be a US ticker")

    def test_lowercase_input(self):
        fn = self._get_fn()
        for code in ("aapl", "tsla", "msft"):
            with self.subTest(code=code):
                self.assertTrue(fn(code), f"{code} (lowercase) should be a US ticker")

    def test_dot_class_share(self):
        fn = self._get_fn()
        for code in ("BRK.B", "RDS.A", "BF.B"):
            with self.subTest(code=code):
                self.assertTrue(fn(code), f"{code} should be a US ticker")

    def test_hyphen_class_share(self):
        """BRK-B style hyphenated tickers (added in this PR)."""
        fn = self._get_fn()
        for code in ("BRK-B", "RDS-A"):
            with self.subTest(code=code):
                self.assertTrue(fn(code), f"{code} should be a US ticker")

    # --- should NOT be recognised as US tickers ---
    def test_a_share_codes(self):
        fn = self._get_fn()
        for code in ("600519", "000001", "300750", "688981"):
            with self.subTest(code=code):
                self.assertFalse(fn(code), f"{code} should NOT be a US ticker")

    def test_hk_codes(self):
        fn = self._get_fn()
        for code in ("hk00700", "HK09988", "00700"):
            with self.subTest(code=code):
                self.assertFalse(fn(code), f"{code} should NOT be a US ticker")

    def test_etf_codes(self):
        fn = self._get_fn()
        for code in ("510300", "159915"):
            with self.subTest(code=code):
                self.assertFalse(fn(code), f"{code} should NOT be a US ticker")

    def test_consistent_across_fetchers(self):
        """All fetcher-local _is_us_code implementations must agree."""
        from data_provider.akshare_fetcher import _is_us_code as fn_ak
        from data_provider.efinance_fetcher import _is_us_code as fn_ef
        from data_provider.pytdx_fetcher import _is_us_code as fn_px
        from data_provider.baostock_fetcher import _is_us_code as fn_bs
        from data_provider.tushare_fetcher import _is_us_code as fn_ts

        test_codes = [
            ("AAPL", True), ("MSFT", True), ("META", True), ("BMNR", True),
            ("CIFR", True), ("AMD", True), ("BRK.B", True), ("BRK-B", True),
            ("600519", False), ("hk00700", False), ("000001", False),
        ]
        for code, expected in test_codes:
            with self.subTest(code=code):
                results = {
                    "akshare": fn_ak(code),
                    "efinance": fn_ef(code),
                    "pytdx": fn_px(code),
                    "baostock": fn_bs(code),
                    "tushare": fn_ts(code),
                }
                for fetcher_name, result in results.items():
                    self.assertEqual(
                        result, expected,
                        f"{fetcher_name}._is_us_code({code!r}) returned {result}, expected {expected}"
                    )


class TestYfinanceConvertCode(unittest.TestCase):
    """Tests for YfinanceFetcher._convert_stock_code."""

    def setUp(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher
        self.fetcher = YfinanceFetcher()

    def test_us_tickers_pass_through(self):
        for code, expected in [
            ("AAPL", "AAPL"), ("tsla", "TSLA"), ("BRK.B", "BRK.B"), ("BRK-B", "BRK-B"),
            ("MSFT", "MSFT"), ("META", "META"), ("BMNR", "BMNR"), ("CIFR", "CIFR"),
        ]:
            with self.subTest(code=code):
                self.assertEqual(self.fetcher._convert_stock_code(code), expected)

    def test_hk_codes_converted(self):
        self.assertEqual(self.fetcher._convert_stock_code("hk00700"), "0700.HK")
        self.assertEqual(self.fetcher._convert_stock_code("HK09988"), "9988.HK")

    def test_a_share_codes_converted(self):
        self.assertEqual(self.fetcher._convert_stock_code("600519"), "600519.SS")
        self.assertEqual(self.fetcher._convert_stock_code("000001"), "000001.SZ")
        self.assertEqual(self.fetcher._convert_stock_code("300750"), "300750.SZ")


class TestDataFetcherManagerUsRouting(unittest.TestCase):
    """
    Tests that DataFetcherManager.get_daily_data tries YfinanceFetcher first
    for US tickers.
    """

    def _make_mock_fetcher(self, name: str, priority: int, return_df=None, raises=None):
        fetcher = MagicMock()
        fetcher.name = name
        fetcher.priority = priority
        if raises:
            fetcher.get_daily_data.side_effect = raises
        else:
            df = return_df if return_df is not None else pd.DataFrame({
                "date": pd.to_datetime(["2024-01-01"]),
                "open": [100.0], "high": [105.0], "low": [99.0],
                "close": [103.0], "volume": [1000000], "amount": [0.0], "pct_chg": [0.0],
            })
            fetcher.get_daily_data.return_value = df
        return fetcher

    def test_yfinance_tried_first_for_us_ticker(self):
        from data_provider.base import DataFetcherManager, DataFetchError

        efinance = self._make_mock_fetcher("EfinanceFetcher", 0, raises=DataFetchError("not supported"))
        akshare = self._make_mock_fetcher("AkshareFetcher", 1, raises=DataFetchError("failed"))
        yfinance = self._make_mock_fetcher("YfinanceFetcher", 4)

        # YfinanceFetcher returns good data
        good_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "open": [150.0], "high": [155.0], "low": [148.0],
            "close": [153.0], "volume": [5000000], "amount": [0.0], "pct_chg": [1.0],
        })
        yfinance.get_daily_data.return_value = good_df

        manager = DataFetcherManager(fetchers=[efinance, akshare, yfinance])
        # After init, fetchers are sorted by priority: EfinanceFetcher(0), AkshareFetcher(1), YfinanceFetcher(4)
        self.assertEqual(manager._fetchers[0].name, "EfinanceFetcher")
        self.assertEqual(manager._fetchers[2].name, "YfinanceFetcher")

        # For US ticker, YfinanceFetcher should be tried FIRST
        df, source = manager.get_daily_data("AAPL")
        self.assertEqual(source, "YfinanceFetcher")
        # YfinanceFetcher must have been called
        yfinance.get_daily_data.assert_called_once()
        # EfinanceFetcher and AkshareFetcher must NOT have been called (YF succeeded first)
        efinance.get_daily_data.assert_not_called()
        akshare.get_daily_data.assert_not_called()

    def test_a_share_keeps_original_priority(self):
        from data_provider.base import DataFetcherManager, DataFetchError

        efinance = self._make_mock_fetcher("EfinanceFetcher", 0)
        akshare = self._make_mock_fetcher("AkshareFetcher", 1)
        yfinance = self._make_mock_fetcher("YfinanceFetcher", 4)

        manager = DataFetcherManager(fetchers=[efinance, akshare, yfinance])
        df, source = manager.get_daily_data("600519")
        # For A-share, EfinanceFetcher (highest priority) should be tried first
        self.assertEqual(source, "EfinanceFetcher")
        efinance.get_daily_data.assert_called_once()
        akshare.get_daily_data.assert_not_called()
        yfinance.get_daily_data.assert_not_called()

    def test_yfinance_fallback_when_empty(self):
        """When YfinanceFetcher fails for a US ticker, AkshareFetcher is the fallback."""
        from data_provider.base import DataFetcherManager, DataFetchError

        akshare_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "open": [10.0], "high": [11.0], "low": [9.0],
            "close": [10.5], "volume": [100000], "amount": [0.0], "pct_chg": [0.5],
        })
        efinance = self._make_mock_fetcher("EfinanceFetcher", 0, raises=DataFetchError("not supported"))
        akshare = self._make_mock_fetcher("AkshareFetcher", 1, return_df=akshare_df)
        yfinance = self._make_mock_fetcher("YfinanceFetcher", 4, raises=DataFetchError("empty data"))

        manager = DataFetcherManager(fetchers=[efinance, akshare, yfinance])
        df, source = manager.get_daily_data("BMNR")
        # YfinanceFetcher tried first, fails; AkshareFetcher succeeds as fallback
        self.assertEqual(source, "AkshareFetcher")
        yfinance.get_daily_data.assert_called_once()
        akshare.get_daily_data.assert_called_once()


if __name__ == "__main__":
    unittest.main()
