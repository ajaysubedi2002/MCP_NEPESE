import json
import re
from typing import Any, Annotated, Literal, Optional
from langsmith import traceable

from nepse_mcp.client import NepseAPIClient
from nepse_mcp.config import settings
from nepse_mcp.resources import ANALYSIS_RULES, MARKET_GLOSSARY
from nepse_mcp.utils import (
    JevAPIError,
    NepseAPIError,
    build_tool_response,
    call_jev_decision,
    clean_ticker,
    summarize_history_gaps,
    to_compact_dividend_record,
    to_compact_live_result,
    to_compact_live_stock,
    to_compact_price_history_record,
    validate_date_format,
)


def register_tools(mcp) -> None:
    """Register all MCP tools on the given FastMCP instance."""

    def traced_tool(*, name: str, description: str):
        def decorator(function):
            traced_function = traceable(
                name=name,
                run_type="tool",
                tags=["mcp", "nepse", name],
            )(function)
            return mcp.tool(name=name, description=description)(traced_function)

        return decorator

    @traced_tool(
        name="get_live_market_data",
        description=(
            "Retrieve current/live trading data (price, volume, high/low, % change) "
            "for a specific NEPSE-listed stock or the entire market. "
            "If analyzing a specific company, always provide the stock_symbol. "
            "Leave stock_symbol empty ONLY when a full market overview is explicitly requested."
        ),
    )
    async def get_live_market_data(
        stock_symbol: Annotated[
            Optional[str],
            "Ticker symbol (e.g., 'NABIL'). Leave empty for all stocks.",
        ] = None,
    ) -> dict:
        """Get current trading data for one stock or the whole market."""
        try:
            clean_symbol = clean_ticker(stock_symbol) if stock_symbol else ""
            async with NepseAPIClient() as client:
                result = await client.get_stock_live(stock_symbol=clean_symbol)
            compact = to_compact_live_result(result)
            return build_tool_response(data=compact.model_dump())
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="search_companies",
        description=(
            "Search the NEPSE company directory by ticker symbol or company name. "
            "Prefer this over reading the full company resource when you only need a few matches."
        ),
    )
    async def search_companies(
        query: Annotated[str, "Partial or exact company name / ticker, e.g. 'NABIL' or 'Nabil'."],
        limit: Annotated[int, "Maximum matches to return, capped at 20."] = 5,
    ) -> dict:
        """Search the company directory with compact match results."""
        try:
            async with NepseAPIClient() as client:
                matches = await client.search_companies(query=query, limit=min(limit, 20))
            return build_tool_response(
                query=query,
                count=len(matches),
                matches=[match.model_dump() for match in matches],
            )
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="get_stock_snapshot",
        description=(
            "Return a compact live snapshot for a single NEPSE stock. "
            "Use this for stock overviews instead of requesting broader live market payloads."
        ),
    )
    async def get_stock_snapshot(
        stock_symbol: Annotated[str, "Ticker symbol (e.g., 'NABIL')."],
    ) -> dict:
        """Get a compact live snapshot for one stock."""
        try:
            async with NepseAPIClient() as client:
                snapshot = await client.get_stock_snapshot(
                    stock_symbol=clean_ticker(stock_symbol)
                )
            return build_tool_response(data=snapshot.model_dump())
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="get_dividend_history",
        description=(
            "Retrieve historical corporate actions, specifically bonus shares, "
            "cash dividends, and rights issuances for a NEPSE-listed company. "
            "Use this to evaluate a company's historical yield and payout consistency. "
            "Check 'has_more_data' in the response; if True, increment 'page_no' to fetch more."
        ),
    )
    async def get_dividend_history(
        stock_symbol: Annotated[str, "Ticker symbol (e.g., 'NABIL')."],
        fiscal_year_id: Annotated[
            int, "Fiscal year ID filter. Default is 0 (returns all fiscal years)."
        ] = 0,
        limit: Annotated[
            int, "Records per page. Max 100. Default to 100 to minimize pagination loops."
        ] = 100,
        page_no: Annotated[int, "Page number to fetch (1-indexed)."] = 1,
    ) -> dict:
        """Get dividend and rights history for a stock."""
        try:
            async with NepseAPIClient() as client:
                page = await client.get_dividend_rights(
                    stock_symbol=clean_ticker(stock_symbol),
                    fiscal_year_id=fiscal_year_id,
                    page_no=page_no,
                    items_per_page=min(limit, 100),
                )
            has_more = page.pager.totalNextPages > 0
            return build_tool_response(
                data_complete=not has_more,
                warning=(
                    "Additional pages are available; increase page_no to fetch more records."
                    if has_more
                    else None
                ),
                source_gap_detected=has_more,
                stock_symbol=clean_ticker(stock_symbol),
                page_no=page.pager.pageNo,
                has_more_data=has_more,
                total_additional_pages=page.pager.totalNextPages,
                records=[to_compact_dividend_record(r).model_dump() for r in page.data],
            )
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="get_price_history",
        description=(
            "Retrieve daily OHLC (Open, High, Low, Close) price history and volume "
            "data for a NEPSE-listed stock over a specified date range. "
            "Crucial for technical analysis and identifying price trends. "
            "Dates MUST be in YYYY-MM-DD format."
        ),
    )
    async def get_price_history(
        stock_symbol: Annotated[str, "Ticker symbol (e.g., 'NICA')."],
        from_date: Annotated[
            str, "Start date in YYYY-MM-DD format (e.g., '2026-01-01')."
        ],
        to_date: Annotated[
            str, "End date in YYYY-MM-DD format (e.g., '2026-09-03')."
        ],
        limit: Annotated[
            int, "Records per page. Max 100. Default to 100 to get more data per call."
        ] = 100,
        page_no: Annotated[int, "Page number (1-indexed)."] = 1,
    ) -> dict:
        """Get daily price history for a stock over a date range."""
        try:
            validate_date_format(from_date)
            validate_date_format(to_date)
        except ValueError as exc:
            return build_tool_response(
                status="error",
                error_message=f"Invalid date format: {exc}",
            )

        try:
            async with NepseAPIClient() as client:
                page = await client.get_stock_history(
                    stock_symbol=clean_ticker(stock_symbol),
                    from_date=from_date,
                    to_date=to_date,
                    page_no=page_no,
                    items_per_page=min(limit, 100),
                )
            has_more = page.pager.totalNextPages > 0
            return build_tool_response(
                data_complete=not has_more,
                warning=(
                    "Additional pages are available; increase page_no to fetch more records."
                    if has_more
                    else None
                ),
                source_gap_detected=has_more,
                stock_symbol=clean_ticker(stock_symbol),
                from_date=from_date,
                to_date=to_date,
                page_no=page.pager.pageNo,
                has_more_data=has_more,
                total_additional_pages=page.pager.totalNextPages,
                records=[
                    to_compact_price_history_record(r).model_dump() for r in page.data
                ],
            )
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="get_price_history_summary",
        description=(
            "Return compact, derived price-history metrics for a single stock over a date range. "
            "Prefer this over raw history when you want trend and performance analysis."
        ),
    )
    async def get_price_history_summary(
        stock_symbol: Annotated[str, "Ticker symbol (e.g., 'NABIL')."],
        from_date: Annotated[str, "Start date in YYYY-MM-DD format."],
        to_date: Annotated[str, "End date in YYYY-MM-DD format."],
    ) -> dict:
        """Get summary metrics for a stock's price history."""
        try:
            validate_date_format(from_date)
            validate_date_format(to_date)
        except ValueError as exc:
            return build_tool_response(
                status="error",
                error_message=f"Invalid date format: {exc}",
            )

        try:
            async with NepseAPIClient() as client:
                summary = await client.get_price_history_summary(
                    stock_symbol=stock_symbol.strip().upper(),
                    from_date=from_date,
                    to_date=to_date,
                )
            data_complete, source_gap_detected, warning = summarize_history_gaps(summary)
            return build_tool_response(
                data=summary.model_dump(),
                data_complete=data_complete,
                warning=warning,
                source_gap_detected=source_gap_detected,
            )
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="get_top_market_movers",
        description=(
            "Retrieve a ranked list of NEPSE stocks by a chosen market indicator. "
            "Use this to find top performing stocks, most actively traded shares, "
            "or highest turnover. Can optionally filter by specific NEPSE sector codes."
        ),
    )
    async def get_top_market_movers(
        indicator: Annotated[
            Literal["gainers", "turnover", "sharestraded"],
            "Ranking metric: 'gainers' (top % change), 'turnover' (total Rs amount), or 'sharestraded' (total volume).",
        ],
        sector_code: Annotated[
            str,
            "Optional sector code filter. Leave empty string for all sectors.",
        ] = "",
        limit: Annotated[
            int,
            "Maximum number of results to return (default 20, max 100).",
        ] = 20,
    ) -> dict:
        """Get top market movers ranked by the chosen indicator."""
        try:
            async with NepseAPIClient() as client:
                movers = await client.get_top_market_movers(
                    indicator=indicator,
                    sector_code=sector_code.strip(),
                    limit=min(limit, 100),
                )
            return build_tool_response(
                indicator=indicator,
                sector_code=sector_code or "all",
                count=len(movers),
                movers=[to_compact_live_stock(m).model_dump() for m in movers],
            )
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="compare_stocks",
        description=(
            "Compare multiple NEPSE stocks by a fixed metric and return ranked compact results. "
            "Use this instead of manually comparing raw payloads."
        ),
    )
    async def compare_stocks(
        stock_symbols: Annotated[list[str], "Ticker symbols to compare, e.g. ['NABIL', 'ADBL']."],
        metric: Annotated[
            Literal["closing_price", "percent_change", "volume", "turnover", "30d_return"],
            "Comparison metric: closing_price, percent_change, volume, turnover, or 30d_return.",
        ],
    ) -> dict:
        """Compare stocks by a compact fixed metric."""
        try:
            unique_symbols = list(
                dict.fromkeys(
                    symbol.strip().upper() for symbol in stock_symbols if symbol.strip()
                )
            )
            async with NepseAPIClient() as client:
                comparison = await client.compare_stocks(
                    stock_symbols=unique_symbols,
                    metric=metric,
                )
            incomplete = len(comparison.rankings) < len(unique_symbols)
            warning = None
            if incomplete:
                warning = (
                    "Some requested symbols could not be ranked because live or history "
                    "data was unavailable."
                )
            return build_tool_response(
                data=comparison.model_dump(),
                data_complete=not incomplete,
                warning=warning,
                source_gap_detected=incomplete,
            )
        except NepseAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @traced_tool(
        name="get_market_glossary",
        description=(
            "Return definitions for NEPSE field names, indicators, sectors, and response flags. "
            "Call this before explaining metrics like turnover, SMA20, or source_gap_detected. "
            "Prefer this tool over nepse://market-glossary when the client cannot read resources."
        ),
    )
    async def get_market_glossary() -> dict:
        """Return the static market glossary as a tool payload."""
        return build_tool_response(data=MARKET_GLOSSARY)

    @traced_tool(
        name="get_analysis_rules",
        description=(
            "Return interpretation rules for momentum, dividends, and common caveats. "
            "Call this before giving analysis explanations so answers stay grounded. "
            "Prefer this tool over nepse://analysis-rules when the client cannot read resources."
        ),
    )
    async def get_analysis_rules() -> dict:
        """Return the static analysis rules as a tool payload."""
        return build_tool_response(data=ANALYSIS_RULES)

    @traced_tool(
        name="evaluate_jev_decision",
        description=(
            "Evaluate arbitrary structured state with Jev System One using choice, score, "
            "or noul questions. Returns Jev's raw probabilistic response."
        ),
    )
    async def evaluate_jev_decision(
        state: Any,
        questions: dict[str, Any],
        model: str = settings.jev_model,
    ) -> dict:
        """Expose the generic Jev decision API without NEPSE-specific assumptions."""
        try:
            return await call_jev_decision(state=state, questions=questions, model=model)
        except JevAPIError as exc:
            return build_tool_response(status="error", error_message=str(exc))

    @mcp.tool(
        name="evaluate_stock_risk_and_momentum",
        description=(
            "Evaluate a stock's historical momentum, volatility, market condition, and "
            "execution safety with Jev. This is an analysis signal, not trade execution."
        ),
    )
    async def evaluate_stock_risk_and_momentum(
        stock_symbol: Annotated[str, "Ticker symbol, e.g. 'NABIL'."],
        from_date: Annotated[str, "Start date in YYYY-MM-DD format."],
        to_date: Annotated[str, "End date in YYYY-MM-DD format."],
    ) -> dict:
        """Build a market-data state and ask Jev for risk and momentum signals."""
        try:
            symbol = clean_ticker(stock_symbol)
            validate_date_format(from_date)
            validate_date_format(to_date)
            async with NepseAPIClient() as client:
                summary = await client.get_price_history_summary(symbol, from_date, to_date)
            state = {
                "symbol": symbol,
                "period": {"from": from_date, "to": to_date},
                "metrics": {
                    "return_pct": summary.percentReturn,
                    "volatility_pct": summary.volatility,
                    "average_volume": summary.averageVolume,
                    "average_turnover": summary.averageTurnover,
                    "latest_price": summary.lastClose,
                    "trend": summary.trend,
                    "volume_trend": summary.volumeTrend,
                    "record_count": summary.recordCount,
                },
            }
            questions = {
                "momentum": {
                    "type": "choice",
                    "instructions": "Classify the stock's price momentum.",
                    "criteria": {
                        "bullish": "Strong positive momentum",
                        "neutral": "Mixed or weakly directional momentum",
                        "bearish": "Negative momentum",
                    },
                },
                "volatility": {
                    "type": "score",
                    "instructions": "Score the volatility risk from 0 to 1.",
                },
                "market_condition": {
                    "type": "choice",
                    "instructions": "Classify the observed market condition.",
                    "criteria": {
                        "favorable": "Positive return and orderly trading",
                        "mixed": "Conflicting or incomplete signals",
                        "unfavorable": "Negative return or stressed trading",
                    },
                },
                "execution_safety": {
                    "type": "noul",
                    "instructions": (
                        "Assess whether the available market data is sufficient for "
                        "automated trade execution; do not issue a trade instruction."
                    ),
                },
            }
            result = await call_jev_decision(state, questions, settings.jev_model)
            return build_tool_response(data=result, jev_state=state, analysis_only=True)
        except ValueError as exc:
            return build_tool_response(status="error", error_message=str(exc))
        except (JevAPIError, NepseAPIError) as exc:
            return build_tool_response(status="error", error_message=str(exc))

    routed_tools = {
        "search_companies",
        "get_stock_snapshot",
        "get_price_history_summary",
        "compare_stocks",
        "get_live_market_data",
        "get_dividend_history",
        "get_top_market_movers",
    }
    routing_questions = {
        "target_tool": {
            "type": "choice",
            "instructions": "Which NEPSE tool is best suited to answer this user query?",
            "criteria": {
                "search_companies": "Search ticker symbols or company names",
                "get_stock_snapshot": "Get current price or a single-stock overview",
                "get_price_history_summary": "Analyze historical prices, trends, returns, or volatility",
                "compare_stocks": "Compare two or more stocks",
                "get_live_market_data": "Get current overall market data",
                "get_dividend_history": "Get dividend, bonus, cash, or fiscal-year history",
                "get_top_market_movers": "Find top gainers, losers, turnover, or volume",
                "llm_fallback": "Ambiguous or multi-step reasoning requests",
            },
        }
    }

    def extract_route_arguments(query: str, tool_name: str) -> dict[str, Any] | None:
        """Extract only simple, unambiguous arguments; never guess complex ones."""
        words = re.findall(r"\b[A-Za-z][A-Za-z0-9.&-]{1,19}\b", query)
        excluded = {"WHAT", "SHOW", "THE", "CURRENT", "PRICE", "OF", "FOR", "AND", "FROM", "TO"}
        symbols = [word.upper() for word in words if word.upper() not in excluded]
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", query)
        if tool_name == "search_companies":
            return {"query": query}
        if tool_name in {"get_stock_snapshot", "get_live_market_data", "get_dividend_history"}:
            if not symbols:
                return None
            return {"stock_symbol": clean_ticker(symbols[0])}
        if tool_name == "get_price_history_summary":
            if not symbols or len(dates) < 2:
                return None
            return {"stock_symbol": clean_ticker(symbols[0]), "from_date": dates[0], "to_date": dates[1]}
        return None

    @mcp.tool(
        name="route_and_process_request",
        description=(
            "Recommended entry point for NEPSE requests. Uses Jev System One for intent "
            "classification and delegates uncertain or complex requests to System Two."
        ),
    )
    async def route_and_process_request(user_query: Annotated[str, "The user's NEPSE request."]) -> dict:
        """Classify a query with Jev and invoke only an allowlisted tool."""
        try:
            jev_result = await call_jev_decision(user_query, routing_questions, settings.jev_model)
        except JevAPIError:
            return {
                "status": "fallback",
                "system": "jev-system-one",
                "reason": "jev_unavailable",
                "next_system": "system-two-llm",
            }
        answer = jev_result.get("answers", {}).get("target_tool")
        if not isinstance(answer, dict):
            return {
                "status": "fallback",
                "system": "jev-system-one",
                "reason": "jev_malformed_response",
                "next_system": "system-two-llm",
            }
        selected_tool = answer.get("choice")
        confidence = answer.get("confidence")
        probabilities = answer.get("probabilities", {})
        if not isinstance(selected_tool, str) or not isinstance(confidence, (int, float)):
            return {
                "status": "fallback",
                "system": "jev-system-one",
                "reason": "jev_malformed_response",
                "next_system": "system-two-llm",
            }
        execution = {
            "status": "delegated",
            "reason": "Jev confidence is below the configured threshold",
            "next_system": "system-two-llm",
        }
        if selected_tool == "llm_fallback":
            execution["reason"] = "Jev selected llm_fallback"
        elif selected_tool in routed_tools and confidence >= settings.jev_confidence_threshold:
            arguments = extract_route_arguments(user_query, selected_tool)
            if arguments is not None:
                result = await mcp.call_tool(selected_tool, arguments)
                routed_data = getattr(result, "data", None)
                if routed_data is None and getattr(result, "content", None):
                    routed_data = json.loads(result.content[0].text)
                return {
                    "status": "routed",
                    "system": "jev-system-one",
                    "selected_tool": selected_tool,
                    "confidence": confidence,
                    "probabilities": probabilities,
                    "execution": {"status": "executed", "tool": selected_tool},
                    "result": routed_data,
                }
            execution["reason"] = "Required tool arguments could not be extracted safely"
        return {
            "status": "fallback",
            "system": "jev-system-one",
            "selected_tool": selected_tool,
            "confidence": confidence,
            "probabilities": probabilities,
            "execution": execution,
        }
