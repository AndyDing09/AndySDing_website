"""Wire tests: pin every alpaca-py contract the live scripts depend on.

No network — these construct the exact request objects the code builds and
assert the SDK symbols/fields exist. If an alpaca-py upgrade renames anything
we use, THIS file fails in seconds instead of the 6:55 AM task failing live.
(Found the hard way: NewsSet exposes .data, not .news, and order_class is not
inferred for brackets.)
"""
import asyncio
import inspect
from datetime import datetime, timezone


def test_trading_client_symbols():
    from alpaca.trading.client import TradingClient
    for m in ("get_clock", "submit_order", "cancel_orders", "close_all_positions",
              "close_position", "get_orders", "replace_order_by_id", "get_account",
              "get_all_assets", "get_all_positions"):
        assert hasattr(TradingClient, m), f"TradingClient.{m} missing"
    from alpaca.trading.models import Clock
    assert {"timestamp", "is_open"} <= set(Clock.model_fields)


def test_bracket_request_constructs_with_explicit_class():
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import (LimitOrderRequest, StopLossRequest,
                                         TakeProfitRequest)
    req = LimitOrderRequest(
        symbol="ABCD", qty=10, side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
        limit_price=5.00, order_class=OrderClass.BRACKET,
        take_profit=TakeProfitRequest(limit_price=6.00),
        stop_loss=StopLossRequest(stop_price=4.50))
    assert req.order_class == OrderClass.BRACKET
    # The SDK does NOT infer bracket from the legs — this is why the broker
    # sets it explicitly. If this ever starts inferring, fine; if a naked
    # (class=None) request with legs becomes invalid, we must know.
    naked = LimitOrderRequest(symbol="ABCD", qty=10, side=OrderSide.BUY,
                              time_in_force=TimeInForce.DAY, limit_price=5.00,
                              take_profit=TakeProfitRequest(limit_price=6.00),
                              stop_loss=StopLossRequest(stop_price=4.50))
    assert naked.order_class is None


def test_broker_source_sets_bracket_class():
    import src.execution.broker as broker
    src_text = inspect.getsource(broker.AlpacaPaperBroker.submit_bracket)
    assert "OrderClass.BRACKET" in src_text


def test_orders_query_and_replace_fields():
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest, ReplaceOrderRequest
    req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=["ABCD"])
    assert req.symbols == ["ABCD"]
    ReplaceOrderRequest(stop_price=4.75)


def test_market_data_contracts():
    from alpaca.data.historical import StockHistoricalDataClient
    for m in ("get_stock_snapshot", "get_stock_bars"):
        assert hasattr(StockHistoricalDataClient, m)
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
    from alpaca.data.timeframe import TimeFrame
    snap_req = StockSnapshotRequest(symbol_or_symbols=["ABCD"], feed="iex")
    assert snap_req.feed == DataFeed.IEX          # plain string coerces
    StockBarsRequest(symbol_or_symbols=["ABCD", "WXYZ"], timeframe=TimeFrame.Day,
                     start=datetime(2026, 6, 1, tzinfo=timezone.utc), feed="iex")
    from alpaca.data.models import Snapshot
    assert {"daily_bar", "previous_daily_bar", "latest_trade"} <= set(Snapshot.model_fields)
    from alpaca.data.models import Bar
    assert {"timestamp", "open", "high", "low", "close", "volume", "symbol"} <= set(Bar.model_fields)


def test_screener_contracts():
    from alpaca.data.historical.screener import ScreenerClient
    assert hasattr(ScreenerClient, "get_most_actives")
    from alpaca.data.models.screener import ActiveStock, MostActives
    assert {"symbol", "volume"} <= set(ActiveStock.model_fields)
    assert "most_actives" in MostActives.model_fields
    from alpaca.data.requests import MostActivesRequest
    MostActivesRequest(top=100)


def test_news_shape_is_data_dict_not_news_attr():
    """The bug that would have shipped an empty watchlist: NewsSet has .data."""
    from alpaca.data.models.news import NewsSet
    assert "data" in NewsSet.model_fields
    assert "news" not in NewsSet.model_fields
    raw = {"news": [{"id": 1, "headline": "ABCD announces FDA approval",
                     "author": "x", "content": "", "summary": "",
                     "created_at": "2026-07-08T11:00:00Z",
                     "updated_at": "2026-07-08T11:00:00Z",
                     "images": [], "source": "benzinga",
                     "symbols": ["ABCD"], "url": "https://example.com"}],
           "next_page_token": None}
    ns = NewsSet(raw_data=raw)
    articles = (ns.data or {}).get("news", [])    # exactly what run_premarket reads
    assert len(articles) == 1
    assert articles[0].headline.startswith("ABCD")
    assert articles[0].created_at.tzinfo is not None


def test_assets_registry_contracts():
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.trading.requests import GetAssetsRequest
    GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY)
    from alpaca.trading.models import Asset
    assert {"symbol", "exchange", "tradable"} <= set(Asset.model_fields)


def test_stream_contracts():
    from alpaca.data.live import StockDataStream
    assert hasattr(StockDataStream, "subscribe_bars")
    assert asyncio.iscoroutinefunction(StockDataStream._run_forever), \
        "session() awaits _run_forever(); if the SDK changed this, rework shutdown"
    assert any(hasattr(StockDataStream, n) for n in ("stop_ws", "stop", "close")), \
        "close_watchdog needs a way to stop the stream at 16:01"
