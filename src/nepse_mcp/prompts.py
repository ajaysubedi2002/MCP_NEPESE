import datetime
import re
from typing import Annotated

from fastmcp.prompts.base import Message
from pydantic import Field


# NEPSE closed days: Saturday (weekday(), sunday  -> Sat=5 Sun = 6)
NEPSE_CLOSED_WEEKDAYS = {5,6}

# Basic sanity check for a stock symbol: letters/numbers only, 1-10 chars.
TICKER_PATTERN = re.compile(r"^[A-Z0-9]{1,10}$")


def register_prompts(mcp) -> None:
    """Register all MCP prompts on the given FastMCP instance."""

    @mcp.prompt(
        name="analyze_nepse_stock",
        description=(
            "Instructs the assistant to perform a technical and dividend-history "
            "analysis of a NEPSE-listed stock by orchestrating tools for live "
            "price, 30-day price history, and dividend records. Does NOT cover "
            "fundamental metrics such as EPS, P/E, or revenue growth."
        ),
    )
    def analyze_nepse_stock(
        ticker: Annotated[
            str,
            Field(
                description=(
                    "NEPSE stock symbol, e.g. 'NABIL' or 'NLIC'. "
                    "Case-insensitive; whitespace is trimmed."
                )
            ),
        ],
    ) -> list[Message]:
        """Return a structured analysis prompt for the given NEPSE ticker."""

        clean_ticker = ticker.strip().upper()

        if not clean_ticker:
            raise ValueError("Ticker symbol cannot be empty.")
        if not TICKER_PATTERN.match(clean_ticker):
            raise ValueError(
                f"Invalid ticker symbol: {ticker!r}. "
                "Expected 1-10 alphanumeric characters (e.g. 'NABIL')."
            )

        today = datetime.date.today()
        thirty_days_ago = today - datetime.timedelta(days=30)

        # Give the LLM an explicit heads-up if "today" is a non-trading day,
        # so stale/last-session data isn't mistaken for an anomaly.
        market_status_note = ""
        if today.weekday() in NEPSE_CLOSED_WEEKDAYS:
            market_status_note = (
                f"\n*Note: {today.strftime('%A')} is a NEPSE non-trading day "
                f"(market is closed sunday and Saturday). Live data will reflect "
                f"the most recent trading session, not intraday activity.*\n"
            )

        prompt_text = (
            f"Act as a technical analyst covering the Nepal Stock Exchange (NEPSE). "
            f"Please perform a price and dividend-history analysis for the ticker "
            f"'{clean_ticker}'.\n\n"
            f"Today's date is {today.isoformat()}."
            f"{market_status_note}\n"
            f"Note: this analysis covers price action and dividend history only. "
            f"It does NOT include fundamental metrics (EPS, P/E, book value, "
            f"revenue/profit growth) — do not fabricate or estimate these.\n\n"
            f"Steps 1-3 call independent tools; call them in parallel if your "
            f"environment supports concurrent tool calls. Step 4 depends on the "
            f"results of all three.\n\n"
            f"### 1. Fetch Live Market Data\n"
            f"Call `get_live_market_data` with stock_symbol='{clean_ticker}'. "
            f"If the tool indicates the symbol is not found or not listed, stop "
            f"immediately and inform the user rather than proceeding to steps 2-3. "
            f"Otherwise, note the current price, trading volume, intraday high/low, "
            f"and percentage change. Report all monetary figures in NPR and clearly "
            f"distinguish volume (shares traded) from turnover (NPR value traded), "
            f"if both are available.\n\n"
            f"### 2. Fetch Recent Price History\n"
            f"Call `get_price_history` with stock_symbol='{clean_ticker}', "
            f"from_date='{thirty_days_ago.isoformat()}', and "
            f"to_date='{today.isoformat()}'. If `has_more_data` is True, fetch at "
            f"most 2 additional pages to extend the trend picture. If more data "
            f"would still be needed beyond that, proceed with the analysis and "
            f"explicitly note that the trend is based on partial data.\n\n"
            f"### 3. Fetch Dividend History\n"
            f"Call `get_dividend_history` with stock_symbol='{clean_ticker}' to "
            f"evaluate long-term shareholder returns (bonus shares and cash "
            f"dividends). If no dividend history exists, state that plainly "
            f"(this is expected for newly listed or non-paying stocks).\n\n"
            f"### 4. Synthesize and Report\n"
            f"Compile your findings into a markdown report with these sections, "
            f"each 2-4 sentences unless a table is specified:\n"
            f"- **Live Snapshot:** Current price, daily performance vs. previous "
            f"close, and volume/turnover context.\n"
            f"- **30-Day Trend Analysis:** Volatility, key support/resistance "
            f"levels, and overall price direction.\n"
            f"- **Dividend Track Record:** Consistency of payouts, presented as a "
            f"markdown table of the recent years (year, cash %, bonus %).\n"
            f"- **Analyst Conclusion:** State clearly whether the stock exhibits "
            f"bullish, bearish, or sideways momentum, based strictly on the data "
            f"gathered above — not on outside knowledge.\n\n"
            f"*Guardrail: If any tool returns empty data or an error, state this "
            f"explicitly in the relevant section rather than estimating or "
            f"inventing values.*"
        )

        return [Message(role="user", content=prompt_text)]