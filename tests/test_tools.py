"""Integration tests for MCP tools and resources using the FastMCP in-process client."""

import json
import pytest
import respx
import httpx
from fastmcp import Client, FastMCP
from fastmcp.server.context import Context
import nepse_mcp.thread_client as thread_client_module
from nepse_mcp.thread_client import ThreadedMCPClient

# Import the mcp instance AFTER all tools/resources are registered
from nepse_mcp.config import settings
from nepse_mcp.main import mcp
from nepse_mcp.tools import get_thread_metadata


# ── Sample payloads ──────────────────────────────────────────────────────────

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
            },
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


# ── Tool tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tool_list_contains_expected_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert "get_live_market_data" in names
    assert "get_dividend_history" in names
    assert "get_price_history" in names
    assert "get_top_market_movers" in names


@pytest.mark.asyncio
async def test_get_live_market_data_tool():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            return_value=httpx.Response(200, json=STOCK_LIVE_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_live_market_data", {"stock_symbol": "ADBL"}
            )

    # FastMCP serialises dict return values as JSON text content
    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert payload["warning"] is None
    assert payload["source_gap_detected"] is False
    assert len(payload["data"]["stocks"]) == 1
    stock = payload["data"]["stocks"][0]
    assert stock["stockSymbol"] == "ADBL"
    assert stock["turnover"] == 1000000.0
    assert stock["dayHigh"] == 500.0
    assert stock["dayLow"] == 490.0
    assert stock["dayChange"] == 3.5
    assert "ltv" not in stock
    assert "dataType" not in stock
    assert "asOfDateString" not in stock
    assert "amount" not in stock
    assert payload["data"]["summary"]["totalTxns"] == 40692


@pytest.mark.asyncio
async def test_get_dividend_history_tool():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetDividendRights").mock(
            return_value=httpx.Response(200, json=DIVIDEND_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_dividend_history", {"stock_symbol": "ADBL"}
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert payload["stock_symbol"] == "ADBL"
    assert payload["has_more_data"] is False
    assert payload["records"][0]["bonus"] == 10.0
    assert "sn" not in payload["records"][0]


@pytest.mark.asyncio
async def test_get_price_history_tool():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=PRICE_HISTORY_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_price_history",
                {
                    "stock_symbol": "ADBL",
                    "from_date": "2026-08-03",
                    "to_date": "2026-09-03",
                },
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert payload["stock_symbol"] == "ADBL"
    assert payload["has_more_data"] is False
    assert payload["records"][0]["closingPrice"] == 498.5
    assert payload["records"][0]["turnover"] == 1000000.0
    assert "sn" not in payload["records"][0]
    assert "amount" not in payload["records"][0]


@pytest.mark.asyncio
async def test_get_price_history_invalid_date_format():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_price_history",
            {
                "stock_symbol": "ADBL",
                "from_date": "03-08-2026",  # wrong format
                "to_date": "2026-09-03",
            },
        )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "error"
    assert "YYYY-MM-DD" in payload["error_message"]


@pytest.mark.asyncio
async def test_get_top_market_movers_tool():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetTopMarketMovers").mock(
            return_value=httpx.Response(200, json=TOP_MOVERS_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_top_market_movers", {"indicator": "gainers"}
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert payload["indicator"] == "gainers"
    assert payload["count"] == 1
    assert payload["movers"][0]["stockSymbol"] == "WNLB"
    assert payload["movers"][0]["turnover"] == 2136884.2
    assert "ltv" not in payload["movers"][0]
    assert "amount" not in payload["movers"][0]


# ── Resource tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_companies_resource_is_listed():
    async with Client(mcp) as client:
        resources = await client.list_resources()
    uris = [str(r.uri) for r in resources]
    assert "nepse://companies" in uris
    assert "nepse://market-glossary" in uris
    assert "nepse://analysis-rules" in uris


@pytest.mark.asyncio
async def test_companies_resource_returns_data():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            return_value=httpx.Response(200, json=COMPANIES_RESPONSE)
        )
        async with Client(mcp) as client:
            contents = await client.read_resource("nepse://companies")

    data = json.loads(contents[0].text)
    assert isinstance(data, list)
    assert data[0]["stockSymbol"] == "ADBL"


@pytest.mark.asyncio
async def test_market_glossary_resource_returns_definitions():
    async with Client(mcp) as client:
        contents = await client.read_resource("nepse://market-glossary")

    data = json.loads(contents[0].text)
    assert "fields" in data
    assert "indicators" in data
    assert "sectors" in data
    assert "closingPrice" in data["fields"]
    assert "gainers" in data["indicators"]


@pytest.mark.asyncio
async def test_analysis_rules_resource_returns_guidance():
    async with Client(mcp) as client:
        contents = await client.read_resource("nepse://analysis-rules")

    data = json.loads(contents[0].text)
    assert "momentum" in data
    assert "dividends" in data
    assert "caveats" in data
    assert isinstance(data["caveats"], list)
    assert len(data["caveats"]) >= 1


# ── Prompt tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prompt_is_listed():
    async with Client(mcp) as client:
        prompts = await client.list_prompts()
    names = {p.name for p in prompts}
    assert "analyze_nepse_stock" in names


@pytest.mark.asyncio
async def test_prompt_returns_messages():
    async with Client(mcp) as client:
        result = await client.get_prompt(
            "analyze_nepse_stock", {"ticker": "NABIL"}
        )
    assert len(result.messages) >= 1
    assert result.messages[0].role == "user"
    # Check that the ticker appears in the prompt content
    content = result.messages[0].content
    text = content.text if hasattr(content, "text") else str(content)
    assert "NABIL" in text

# Add a test for the compact tools.
@pytest.mark.asyncio
async def test_tool_list_contains_compact_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert "search_companies" in names
    assert "get_stock_snapshot" in names
    assert "get_price_history_summary" in names
    assert "compare_stocks" in names
    assert "get_market_glossary" in names
    assert "get_analysis_rules" in names


@pytest.mark.asyncio
async def test_get_market_glossary_tool():
    async with Client(mcp) as client:
        result = await client.call_tool("get_market_glossary", {})

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert "fields" in payload["data"]
    assert "indicators" in payload["data"]
    assert "source_gap_detected" in payload["data"]["response_flags"]
    assert payload["data"]["fields"]["turnover"].startswith("Total traded value")


@pytest.mark.asyncio
async def test_get_analysis_rules_tool():
    async with Client(mcp) as client:
        result = await client.call_tool("get_analysis_rules", {})

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert "momentum" in payload["data"]
    assert "dividends" in payload["data"]
    assert "caveats" in payload["data"]
    assert isinstance(payload["data"]["caveats"], list)
    assert len(payload["data"]["caveats"]) >= 1


@pytest.mark.asyncio
async def test_search_companies_tool():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            return_value=httpx.Response(200, json=COMPANIES_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool("search_companies", {"query": "ADBL"})

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["matches"][0]["stockSymbol"] == "ADBL"
    assert payload["matches"][0]["matchType"] == "exact_symbol"


@pytest.mark.asyncio
async def test_get_stock_snapshot_tool():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            return_value=httpx.Response(200, json=STOCK_LIVE_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_stock_snapshot", {"stock_symbol": "ADBL"}
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert payload["warning"] is None
    assert payload["source_gap_detected"] is False
    assert payload["data"]["stockSymbol"] == "ADBL"
    assert payload["data"]["dayHigh"] == 500.0
    assert "ltv" not in payload["data"]
    assert "dataType" not in payload["data"]
    assert "asOfDateString" not in payload["data"]


@pytest.mark.asyncio
async def test_get_price_history_summary_tool():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=LONG_PRICE_HISTORY_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_price_history_summary",
                {
                    "stock_symbol": "ADBL",
                    "from_date": "2026-08-01",
                    "to_date": "2026-08-03",
                },
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is True
    assert payload["warning"] is None
    assert payload["source_gap_detected"] is False
    assert payload["data"]["recordCount"] == 30
    assert payload["data"]["percentReturn"] == 43.0
    assert payload["data"]["dayChange"] == 2.0
    assert payload["data"]["dayChangePercent"] == 1.42
    assert payload["data"]["sevenDayReturn"] == 8.33
    assert payload["data"]["thirtyDayReturn"] == 43.0
    assert payload["data"]["sma5"] == 139.0
    assert payload["data"]["sma10"] == 135.3
    assert payload["data"]["sma20"] == 127.65
    assert payload["data"]["maxDrawdown"] == 0.96
    assert payload["data"]["volumeTrend"] == "increasing"


@pytest.mark.asyncio
async def test_evaluate_stock_risk_and_momentum_returns_metrics_for_llm():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=LONG_PRICE_HISTORY_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "evaluate_stock_risk_and_momentum",
                {
                    "stock_symbol": "ADBL",
                    "from_date": "2026-08-01",
                    "to_date": "2026-08-03",
                },
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["analysis_only"] is True
    assert payload["data"]["stockSymbol"] == "ADBL"
    assert payload["data"]["percentReturn"] == 43.0
    assert payload["analysis_state"]["metrics"]["trend"] == "increasing"


@pytest.mark.asyncio
async def test_get_price_history_summary_marks_incomplete_for_short_history():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(200, json=PRICE_HISTORY_SUMMARY_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_price_history_summary",
                {
                    "stock_symbol": "ADBL",
                    "from_date": "2026-08-01",
                    "to_date": "2026-08-03",
                },
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data_complete"] is False
    assert payload["source_gap_detected"] is True
    assert payload["warning"] is not None
    assert "SMA" in payload["warning"] or "unavailable" in payload["warning"].lower()
    assert payload["data"]["sma20"] is None
    assert payload["data"]["thirtyDayReturn"] is None


@pytest.mark.asyncio
async def test_compare_stocks_tool():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
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
        async with Client(mcp) as client:
            result = await client.call_tool(
                "compare_stocks",
                {"stock_symbols": ["ADBL", "NABIL"], "metric": "percent_change"},
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data"]["metric"] == "percent_change"
    assert payload["data"]["rankings"][0]["stockSymbol"] == "NABIL"


@pytest.mark.asyncio
async def test_compare_stocks_tool_uses_thirty_day_return():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            side_effect=[
                httpx.Response(200, json=LONG_PRICE_HISTORY_RESPONSE),
                httpx.Response(200, json=LONG_PRICE_HISTORY_RESPONSE),
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
        async with Client(mcp) as client:
            result = await client.call_tool(
                "compare_stocks",
                {"stock_symbols": ["ADBL", "NABIL"], "metric": "30d_return"},
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["data"]["metric"] == "30d_return"
    assert all(item["value"] == 43.0 for item in payload["data"]["rankings"])


@pytest.mark.asyncio
async def test_search_companies_tool_returns_empty_matches():
    with respx.mock:
        respx.post("https://nepalipaisa.com/api/GetCompanies").mock(
            return_value=httpx.Response(200, json=COMPANIES_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "search_companies", {"query": "NOPE", "limit": 5}
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "success"
    assert payload["count"] == 0
    assert payload["matches"] == []


@pytest.mark.asyncio
async def test_get_price_history_summary_tool_invalid_date():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_price_history_summary",
            {
                "stock_symbol": "ADBL",
                "from_date": "08-01-2026",
                "to_date": "2026-08-03",
            },
        )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "error"
    assert "YYYY-MM-DD" in payload["error_message"]


@pytest.mark.asyncio
async def test_get_price_history_summary_tool_empty_history():
    with respx.mock:
        respx.get("https://nepalipaisa.com/api/GetStockHistory").mock(
            return_value=httpx.Response(
                200,
                json={
                    "statusCode": 200,
                    "message": "Success",
                    "result": {
                        "data": [],
                        "pager": {
                            "pageNo": 1,
                            "itemsPerPage": 100,
                            "pagePerDisplay": 5,
                            "totalNextPages": 0,
                        },
                    },
                },
            )
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_price_history_summary",
                {
                    "stock_symbol": "ADBL",
                    "from_date": "2026-08-01",
                    "to_date": "2026-08-03",
                },
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "error"
    assert "No price history found" in payload["error_message"]


@pytest.mark.asyncio
async def test_route_and_process_request_executes_high_confidence_tool(monkeypatch):
    monkeypatch.setattr(settings, "jevmodel_api_key", "test-key")
    with respx.mock:
        respx.post(settings.jev_api_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "answers": {
                        "target_tool": {
                            "type": "choice",
                            "choice": "get_stock_snapshot",
                            "confidence": 0.91,
                            "probabilities": {"get_stock_snapshot": 0.91},
                        }
                    },
                },
            )
        )
        respx.get("https://nepalipaisa.com/api/GetStockLive").mock(
            return_value=httpx.Response(200, json=STOCK_LIVE_RESPONSE)
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "route_and_process_request", {"user_query": "What is the current price of NABIL?"}
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "routed"
    assert payload["selected_tool"] == "get_stock_snapshot"
    assert payload["execution"]["status"] == "executed"


@pytest.mark.asyncio
async def test_route_and_process_request_falls_back_on_low_confidence(monkeypatch):
    monkeypatch.setattr(settings, "jevmodel_api_key", "test-key")
    with respx.mock:
        respx.post(settings.jev_api_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "answers": {
                        "target_tool": {
                            "type": "choice",
                            "choice": "get_stock_snapshot",
                            "confidence": 0.42,
                        }
                    }
                },
            )
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "route_and_process_request", {"user_query": "Tell me something about NABIL."}
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "fallback"
    assert payload["execution"]["next_system"] == "system-two-llm"


@pytest.mark.asyncio
async def test_route_and_process_request_executes_compare_stocks(monkeypatch):
    monkeypatch.setattr(settings, "jevmodel_api_key", "test-key")
    captured_call = {}
    original_call_tool = mcp.call_tool

    async def fake_call_tool(name, arguments=None, **kwargs):
        if name == "compare_stocks":
            captured_call["name"] = name
            captured_call["arguments"] = arguments
            return {"status": "success", "data": {"metric": "closing_price"}}
        return await original_call_tool(name, arguments, **kwargs)

    monkeypatch.setattr(mcp, "call_tool", fake_call_tool)
    with respx.mock:
        respx.post(settings.jev_api_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "answers": {
                        "target_tool": {
                            "type": "choice",
                            "choice": "compare_stocks",
                            "confidence": 0.95,
                        }
                    }
                },
            )
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "route_and_process_request",
                {"user_query": "Compare UPPER and NABIL by closing price"},
            )

    payload = json.loads(result.content[0].text)
    assert payload["status"] == "routed"
    assert captured_call == {
        "name": "compare_stocks",
        "arguments": {
            "stock_symbols": ["UPPER", "NABIL"],
            "metric": "closing_price",
        },
    }


class RecordingMCPClient:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments=None, **kwargs):
        self.calls.append((name, arguments, kwargs))
        return {"status": "ok"}


@pytest.mark.asyncio
async def test_thread_client_reuses_id_until_new_thread():
    underlying_client = RecordingMCPClient()
    client = ThreadedMCPClient(underlying_client)

    await client.call_tool("first", {"value": 1})
    first_id = client.thread_id
    await client.call_tool("second", {"value": 2}, meta={"unrelated": "value"})
    second_id = client.thread_id

    assert first_id == second_id
    assert underlying_client.calls[0][2]["meta"] == {"thread_id": first_id}
    assert underlying_client.calls[1][2]["meta"] == {
        "unrelated": "value",
        "thread_id": first_id,
    }

    new_id = client.start_new_thread()
    await client.call_tool("third")

    assert new_id != first_id
    assert underlying_client.calls[2][2]["meta"] == {"thread_id": new_id}


@pytest.mark.asyncio
async def test_thread_id_reaches_server_request_metadata():
    probe_server = FastMCP(name="conversation-probe")

    @probe_server.tool
    async def read_conversation_metadata(ctx: Context) -> dict:
        return get_thread_metadata()

    async with ThreadedMCPClient(Client(probe_server)) as client:
        result = await client.call_tool("read_conversation_metadata")

    payload = json.loads(result.content[0].text)
    assert payload["thread_id"] == client.thread_id


@pytest.mark.asyncio
async def test_run_chat_turn_passes_user_query_and_thread_id(monkeypatch):
    def fake_traceable(**_):
        def decorator(function):
            async def wrapped(*args, **kwargs):
                return await function(*args)

            return wrapped

        return decorator

    monkeypatch.setattr(
        thread_client_module,
        "traceable",
        fake_traceable,
    )
    underlying_client = RecordingMCPClient()
    client = ThreadedMCPClient(underlying_client)

    await client.run_chat_turn("What is the current price of NABIL?")

    assert underlying_client.calls == [
        (
            "route_and_process_request",
            {"user_query": "What is the current price of NABIL?"},
            {"meta": {"thread_id": client.thread_id}},
        )
    ]
