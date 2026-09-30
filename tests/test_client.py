"""Tests for NepseAPIClient using respx HTTP mocks."""

from datetime import date, timedelta
import pytest
import respx
import httpx

from nepse_mcp.client import NepseAPIClient
from nepse_mcp.utils import NepseAPIError


# ── Sample payloads (trimmed from API docs) ──────────────────────────────────

COMPANIES_RESPONSE = {
    "statusCode": 200,
    "message": "Success",
    "result": [
        {
            "companyId": 1,
            "companyName": "Agricultural Development Bank Limited",
            "stockSymbol": "ADBL",
            "sectorId": 0,
            "sectorName": "Commercial Banks",
        }
    ],
}

STOCK_LIVE_RESPONSE = {
    "statusCode": 200,
    "message": "Success",
    "result": {
        "stocks": [
            {
                "stockSymbol": "ADBL",
                "companyName": "Agricultural Development Bank Limited",
                "noOfTransactions": 50,
                "maxPrice": 500.0,
                "minPrice": 490.0,
                "openingPrice": 492.0,
                "closingPrice": 498.5,
                "amount": 1000000.0,
                "previousClosing": 495.0,
                "differenceRs": 3.5,
                "percentChange": 0.71,
                "volume": 2000,
                "ltv": 0,
                "asOfDate": "2026-09-03T15:00:00",
                "asOfDateString": "As of Thu, 03 Sep 2026 | 03:00:00 PM",
                "tradeDate": "2026-09-03",
                "dataType": None,
            }
        ],
        "summary": {
            "totalAmount": 3465201042.79,
            "totalShares": 12163763,
            "totalTxns": 40692,
        },
    },
}

DIVIDEND_RESPONSE = {
    "statusCode": 200,
    "message": "Success",
    "result": {
        "data": [
            {
                "sn": 1,
                "companyName": "Agricultural Development Bank Limited",
                "stockSymbol": "ADBL",
                "bonus": "10.00",
                "cash": "5.00",
                "totalDividend": "15.00",
                "bookClosureDateAD": "2022-03-31",
                "bookClosureDateBS": "2078-12-17",
                "fiscalYearAD": "2020/2021",
                "fiscalYearBS": "2077/2078",
                "rightShare": None,
                "rightBookCloseDateAD": None,
                "rightBookCloseDateBS": None,
            }
        ],
        "pager": {
            "pageNo": 1,
            "itemsPerPage": 20,
            "pagePerDisplay": 5,
            "totalNextPages": 0,
        },
    },
}

PRICE_HISTORY_RESPONSE = {
    "statusCode": 200,
    "message": "Success",
    "result": {
        "data": [
            {
                "sn": 1,
                "tradeDate": "2026-09-03T00:00:00",
                "tradeDateString": "2026-09-03",
                "maxPrice": 500.0,
                "minPrice": 490.0,
                "closingPrice": 498.5,
                "noOfTransactions": 50,
                "volume": 2000,
                "amount": 1000000.0,
                "previousClosing": 495.0,
                "differenceRs": 3.5,
                "percentChange": 0.71,
            }
        ],
        "pager": {
            "pageNo": 1,
            "itemsPerPage": 20,
            "pagePerDisplay": 5,
            "totalNextPages": 2,
        },
    },
}

# Add a test for the price history summary response.
PRICE_HISTORY_SUMMARY_RESPONSE = {
    "statusCode": 200,
    "message": "Success",
    "result": {
        "data": [
            {
                "sn": 1,
                "tradeDate": "2026-08-01T00:00:00",
                "tradeDateString": "2026-08-01",
                "maxPrice": 101.0,
                "minPrice": 99.0,
                "closingPrice": 100.0,
                "noOfTransactions": 10,
                "volume": 1000,
                "amount": 100000.0,
                "previousClosing": 98.0,
                "differenceRs": 2.0,
                "percentChange": 2.04,
            },
            {
                "sn": 2,
                "tradeDate": "2026-08-02T00:00:00",
                "tradeDateString": "2026-08-02",
                "maxPrice": 106.0,
                "minPrice": 102.0,
                "closingPrice": 105.0,
                "noOfTransactions": 14,
                "volume": 1500,
                "amount": 157500.0,
                "previousClosing": 100.0,
                "differenceRs": 5.0,
                "percentChange": 5.0,
            },
            {
                "sn": 3,
                "tradeDate": "2026-08-03T00:00:00",
                "tradeDateString": "2026-08-03",
                "maxPrice": 111.0,
                "minPrice": 107.0,
                "closingPrice": 110.0,
                "noOfTransactions": 20,
                "volume": 1200,
                "amount": 132000.0,
                "previousClosing": 105.0,
                "differenceRs": 5.0,
                "percentChange": 4.76,
            }
        ],
        "pager": {
            "pageNo": 1,
            "itemsPerPage": 100,
            "pagePerDisplay": 5,
            "totalNextPages": 0,
        },
    },
}

LONG_PRICE_HISTORY_RESPONSE = {
    "statusCode": 200,
    "message": "Success",
    "result": {
        "data": [
            {
                "sn": idx + 1,
                "tradeDate": f"2026-08-{idx + 1:02d}T00:00:00",
                "tradeDateString": f"2026-08-{idx + 1:02d}",
                "maxPrice": float(close + 1),
                "minPrice": float(close - 1),
                "closingPrice": float(close),
                "noOfTransactions": 10 + idx,
                "volume": volume,
                "amount": float(close * volume),
                "previousClosing": float(prev_close),
                "differenceRs": float(close - prev_close),
                "percentChange": round(((close - prev_close) / prev_close) * 100, 2),
            }
            for idx, (close, prev_close, volume) in enumerate(
                [
                    (100, 99, 1000),
                    (102, 100, 1050),
                    (104, 102, 1100),
                    (103, 104, 1150),
                    (106, 103, 1200),
                    (108, 106, 1250),
                    (107, 108, 1300),
                    (109, 107, 1400),
                    (111, 109, 1500),
                    (110, 111, 1600),
                    (112, 110, 1700),
                    (115, 112, 1800),
                    (117, 115, 1900),
                    (118, 117, 2000),
                    (120, 118, 2200),
                    (119, 120, 2400),
                    (121, 119, 2600),
                    (124, 121, 2800),
                    (126, 124, 3000),
                    (128, 126, 3200),
                    (127, 128, 3400),
                    (129, 127, 3600),
                    (132, 129, 3800),
                    (134, 132, 4000),
                    (136, 134, 4200),
                    (135, 136, 4400),
                    (137, 135, 4600),
                    (139, 137, 4800),
                    (141, 139, 5000),
                    (143, 141, 5200),
                ]
            )
        ],
        "pager": {
            "pageNo": 1,
            "itemsPerPage": 100,
            "pagePerDisplay": 5,
            "totalNextPages": 0,
        },
    },
}

TOP_MOVERS_RESPONSE = {
    "statusCode": 200,
    "message": "Success",
    "result": [
        {
            "stockSymbol": "WNLB",
            "companyName": "Wean Nepal Laghubitta",
            "noOfTransactions": 79,
            "maxPrice": 1099.0,
            "minPrice": 971.1,
            "openingPrice": 971.1,
            "closingPrice": 1055.0,
            "amount": 2136884.2,
            "previousClosing": 970.0,
            "differenceRs": 85.0,
            "percentChange": 8.76,
            "volume": 2068,
            "ltv": 0,
            "asOfDate": "2026-09-03T15:00:00",
            "asOfDateString": "As of Thu, 03 Sep 2026 | 03:00:00 PM",
            "tradeDate": "2026-09-03",
            "dataType": "gainer",
        }
    ],
}

ERROR_BODY_RESPONSE = {
    "statusCode": 400,
    "message": "Bad Request",
    "result": None,
}


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_companies_happy_path():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            return_value=httpx.Response(200, json=COMPANIES_RESPONSE)
        )
        async with NepseAPIClient() as client:
            companies = await client.get_companies()

    assert len(companies) == 1
    assert companies[0].stockSymbol == "ADBL"
    assert companies[0].sectorName == "Commercial Banks"


@pytest.mark.asyncio
async def test_get_stock_live_happy_path():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            return_value=httpx.Response(200, json=STOCK_LIVE_RESPONSE)
        )
        async with NepseAPIClient() as client:
            result = await client.get_stock_live(stock_symbol="ADBL")

    assert len(result.stocks) == 1
    assert result.stocks[0].stockSymbol == "ADBL"
    assert result.stocks[0].closingPrice == 498.5
    assert result.summary is not None
    assert result.summary.totalTxns == 40692


@pytest.mark.asyncio
async def test_get_dividend_rights_happy_path():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetDividendRights").mock(
            return_value=httpx.Response(200, json=DIVIDEND_RESPONSE)
        )
        async with NepseAPIClient() as client:
            page = await client.get_dividend_rights(stock_symbol="ADBL")

    assert len(page.data) == 1
    record = page.data[0]
    assert record.stockSymbol == "ADBL"
    # Verify string → float conversion
    assert record.bonus == 10.0
    assert record.cash == 5.0
    assert record.totalDividend == 15.0
    assert page.pager.totalNextPages == 0


@pytest.mark.asyncio
async def test_get_stock_history_happy_path():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=PRICE_HISTORY_RESPONSE)
        )
        async with NepseAPIClient() as client:
            page = await client.get_stock_history(
                stock_symbol="ADBL",
                from_date="2026-08-03",
                to_date="2026-09-03",
            )

    assert len(page.data) == 1
    assert page.data[0].closingPrice == 498.5
    # has_more_data flag logic (totalNextPages == 2 → True)
    assert page.pager.totalNextPages == 2


@pytest.mark.asyncio
async def test_get_top_market_movers_happy_path():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetTopMarketMovers").mock(
            return_value=httpx.Response(200, json=TOP_MOVERS_RESPONSE)
        )
        async with NepseAPIClient() as client:
            movers = await client.get_top_market_movers(indicator="gainers")

    assert len(movers) == 1
    assert movers[0].stockSymbol == "WNLB"
    assert movers[0].dataType == "gainer"


@pytest.mark.asyncio
async def test_non_200_status_code_in_body_raises_error():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            return_value=httpx.Response(200, json=ERROR_BODY_RESPONSE)
        )
        async with NepseAPIClient() as client:
            with pytest.raises(NepseAPIError, match="statusCode=400"):
                await client.get_companies()


@pytest.mark.asyncio
async def test_http_error_raises_nepse_api_error():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            return_value=httpx.Response(500)
        )
        async with NepseAPIClient() as client:
            with pytest.raises(NepseAPIError, match="HTTP 500"):
                await client.get_companies()


@pytest.mark.asyncio
async def test_timeout_raises_nepse_api_error():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        async with NepseAPIClient() as client:
            with pytest.raises(NepseAPIError, match="timed out"):
                await client.get_companies()


@pytest.mark.asyncio
async def test_search_companies_prefers_exact_symbol_match():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            return_value=httpx.Response(
                200,
                json={
                    "statusCode": 200,
                    "message": "Success",
                    "result": [
                        {
                            "companyId": 1,
                            "companyName": "Agricultural Development Bank Limited",
                            "stockSymbol": "ADBL",
                            "sectorId": 0,
                            "sectorName": "Commercial Banks",
                        },
                        {
                            "companyId": 2,
                            "companyName": "Aadbl Finance Limited",
                            "stockSymbol": "AADBL",
                            "sectorId": 1,
                            "sectorName": "Finance",
                        },
                    ],
                },
            )
        )
        async with NepseAPIClient() as client:
            matches = await client.search_companies("adbl", limit=2)

    assert [match.stockSymbol for match in matches] == ["ADBL", "AADBL"]


@pytest.mark.asyncio
async def test_get_stock_snapshot_returns_compact_view():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            return_value=httpx.Response(200, json=STOCK_LIVE_RESPONSE)
        )
        async with NepseAPIClient() as client:
            snapshot = await client.get_stock_snapshot("adbl")

    assert snapshot.stockSymbol == "ADBL"
    assert snapshot.companyName == "Agricultural Development Bank Limited"
    assert snapshot.closingPrice == 498.5
    assert snapshot.dayHigh == 500.0
    assert snapshot.dayLow == 490.0


@pytest.mark.asyncio
async def test_get_price_history_summary_computes_metrics():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=PRICE_HISTORY_SUMMARY_RESPONSE)
        )
        async with NepseAPIClient() as client:
            summary = await client.get_price_history_summary(
                stock_symbol="ADBL",
                from_date="2026-08-01",
                to_date="2026-08-03",
            )

    assert summary.stockSymbol == "ADBL"
    assert summary.recordCount == 3
    assert summary.firstClose == 100.0
    assert summary.lastClose == 110.0
    assert summary.absoluteReturn == 10.0
    assert summary.percentReturn == 10.0
    assert summary.averageVolume == 1233.33
    assert summary.highestClose == 110.0
    assert summary.lowestClose == 100.0
    assert summary.trend == "uptrend"


@pytest.mark.asyncio
async def test_get_price_history_summary_computes_extended_analytics():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=LONG_PRICE_HISTORY_RESPONSE)
        )
        async with NepseAPIClient() as client:
            summary = await client.get_price_history_summary(
                stock_symbol="ADBL",
                from_date="2026-08-01",
                to_date="2026-08-30",
            )

    assert summary.dayChange == 2.0
    assert summary.dayChangePercent == 1.42
    assert summary.sevenDayReturn == 8.33
    assert summary.thirtyDayReturn == 43.0
    assert summary.sma5 == 139.0
    assert summary.sma10 == 135.3
    assert summary.sma20 == 127.65
    assert summary.maxDrawdown == 0.96
    assert summary.volumeTrend == "increasing"


@pytest.mark.asyncio
async def test_compare_stocks_ranks_by_percent_change():
    with respx.mock:
        route = respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "statusCode": 200,
                        "message": "Success",
                        "result": {
                            "stocks": [
                                {**STOCK_LIVE_RESPONSE["result"]["stocks"][0], "stockSymbol": "ADBL", "percentChange": 0.71}
                            ]
                        },
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "statusCode": 200,
                        "message": "Success",
                        "result": {
                            "stocks": [
                                {**STOCK_LIVE_RESPONSE["result"]["stocks"][0], "stockSymbol": "NABIL", "percentChange": 1.2}
                            ]
                        },
                    },
                ),
            ]
        )
        async with NepseAPIClient() as client:
            comparison = await client.compare_stocks(["ADBL", "NABIL"], metric="percent_change")

    assert route.called
    assert comparison.metric == "percent_change"
    assert [item.stockSymbol for item in comparison.rankings] == ["NABIL", "ADBL"]


@pytest.mark.asyncio
async def test_compare_stocks_uses_thirty_day_return_metric():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            side_effect=[
                httpx.Response(200, json=LONG_PRICE_HISTORY_RESPONSE),
                httpx.Response(
                    200,
                    json={
                        **LONG_PRICE_HISTORY_RESPONSE,
                        "result": {
                            **LONG_PRICE_HISTORY_RESPONSE["result"],
                            "data": [
                                {**row, "stockSymbol": "NABIL"} if "stockSymbol" in row else row
                                for row in LONG_PRICE_HISTORY_RESPONSE["result"]["data"]
                            ],
                        },
                    },
                ),
            ]
        )
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            side_effect=[
                httpx.Response(200, json=STOCK_LIVE_RESPONSE),
                httpx.Response(
                    200,
                    json={
                        "statusCode": 200,
                        "message": "Success",
                        "result": {
                            "stocks": [
                                {
                                    **STOCK_LIVE_RESPONSE["result"]["stocks"][0],
                                    "stockSymbol": "NABIL",
                                    "companyName": "Nabil Bank Limited",
                                }
                            ]
                        },
                    },
                ),
            ]
        )
        async with NepseAPIClient() as client:
            comparison = await client.compare_stocks(
                ["ADBL", "NABIL"], metric="30d_return"
            )

    assert comparison.metric == "30d_return"
    assert len(comparison.rankings) == 2
    assert all(item.value == 43.0 for item in comparison.rankings)


@pytest.mark.asyncio
async def test_compare_stocks_thirty_day_return_uses_rolling_window():
    today = date.today()
    expected_from = (today - timedelta(days=30)).isoformat()
    expected_to = today.isoformat()

    with respx.mock:
        history_route = respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=LONG_PRICE_HISTORY_RESPONSE)
        )
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            return_value=httpx.Response(200, json=STOCK_LIVE_RESPONSE)
        )
        async with NepseAPIClient() as client:
            await client.compare_stocks(["ADBL"], metric="30d_return")

    assert history_route.called
    params = history_route.calls[0].request.url.params
    assert params["fromDate"] == expected_from
    assert params["toDate"] == expected_to
