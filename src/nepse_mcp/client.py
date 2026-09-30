import math
import time
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from nepse_mcp.config import settings
from nepse_mcp.schemas import (
    CompareMetric,
    Company,
    CompanySearchHit,
    DividendRecord,
    IndicatorType,
    LiveMarketResult,
    PaginatedData,
    Pager,
    PriceHistorySummary,
    PriceHistoryRecord,
    StockComparisonItem,
    StockComparisonResult,
    StockSnapshot,
    TopMoverItem,
)
from nepse_mcp.utils import NepseAPIError


class NepseAPIClient:
    """Async client that wraps all NepaliPaisa API endpoints.

    Usage (as async context manager):
        async with NepseAPIClient() as client:
            companies = await client.get_companies()
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._http: httpx.AsyncClient | None = client
        self._external_client: bool = client is not None

    async def __aenter__(self) -> "NepseAPIClient":
        if self._http is None:
            # Set explicit User-Agent and headers to avoid being blocked or rate-limited by API anti-scraping
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            }
            self._http = httpx.AsyncClient(
                base_url=str(settings.nepalipaisa_base_url).rstrip("/"),
                timeout=settings.nepse_http_timeout,
                headers=headers,
                follow_redirects=True,
            )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._http is not None and not self._external_client:
            await self._http.aclose()
            self._http = None

    # Private helpers
    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError(
                "NepseAPIClient is not open. Use it as an async context manager."
            )
        return self._http

    @staticmethod
    def _cache_bust() -> int:
        """Return the current epoch time in milliseconds for cache-busting."""
        return int(time.time() * 1000)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a GET request and validate the response envelope.

        Returns:
            The `result` field from the response JSON.

        Raises:
            NepseAPIError: On HTTP errors, timeouts, or non-200 statusCode in the body.
        """
        if params is None:
            params = {}
        
        if not path.startswith("/"):
            path = f"/{path}"

        params["_"] = self._cache_bust()

        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise NepseAPIError(
                f"Request to {path} timed out after {settings.nepse_http_timeout}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise NepseAPIError(
                f"HTTP {exc.response.status_code} error from {path}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise NepseAPIError(f"Network error connecting to NEPSE API: {exc}") from exc

        try:
            body = response.json()
        except Exception as exc:
            raise NepseAPIError(f"Failed to parse JSON response from {path}: {exc}") from exc

        if not isinstance(body, dict):
            raise NepseAPIError(f"Invalid API response format from {path}: expected JSON object.")

        status_code = body.get("statusCode")
        if status_code is not None and status_code != 200:
            message = body.get("message", "Unknown API error")
            raise NepseAPIError(
                f"API returned statusCode={status_code}: {message}",
                status_code=status_code if isinstance(status_code, int) else None,
            )

        return body.get("result")

    async def _post(self, path: str, payload: Any) -> Any:
        """Execute a POST request and validate the response envelope."""
        if not path.startswith("/"):
            path = f"/{path}"

        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise NepseAPIError(
                f"Request to {path} timed out after {settings.nepse_http_timeout}s."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise NepseAPIError(
                f"HTTP {exc.response.status_code} error from {path}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise NepseAPIError(f"Network error connecting to NEPSE API: {exc}") from exc

        try:
            body = response.json()
        except Exception as exc:
            raise NepseAPIError(f"Failed to parse JSON response from {path}: {exc}") from exc

        if not isinstance(body, dict):
            raise NepseAPIError(f"Invalid API response format from {path}: expected JSON object.")

        status_code = body.get("statusCode")
        if status_code is not None and status_code != 200:
            message = body.get("message", "Unknown API error")
            raise NepseAPIError(
                f"API returned statusCode={status_code}: {message}",
                status_code=status_code if isinstance(status_code, int) else None,
            )

        return body.get("result")

    # Public endpoint methods

    async def get_companies(self) -> list[Company]:
        """POST /GetCompanies — full list of NEPSE-listed companies."""
        result = await self._post("/GetCompanies", [])
        if not isinstance(result, list):
            return []
        return [Company.model_validate(item) for item in result]

    async def search_companies(self, query: str, limit: int = 5) -> list[CompanySearchHit]:
        """Search companies by symbol or company name with exact-symbol preference."""
        clean_query = query.strip().upper()
        if not clean_query:
            return []

        companies = await self.get_companies()
        exact_symbol_matches: list[CompanySearchHit] = []
        prefix_symbol_matches: list[CompanySearchHit] = []
        name_matches: list[CompanySearchHit] = []

        for company in companies:
            symbol = company.stockSymbol.upper()
            name = company.companyName.upper()

            if symbol == clean_query:
                exact_symbol_matches.append(
                    CompanySearchHit(**company.model_dump(), matchType="exact_symbol")
                )
            elif symbol.startswith(clean_query):
                prefix_symbol_matches.append(
                    CompanySearchHit(**company.model_dump(), matchType="prefix_symbol")
                )
            elif clean_query in name:
                name_matches.append(
                    CompanySearchHit(**company.model_dump(), matchType="name_match")
                )

        ranked_matches = exact_symbol_matches + prefix_symbol_matches + name_matches
        return ranked_matches[: max(1, min(limit, 20))]

    async def get_stock_live(self, stock_symbol: str = "") -> LiveMarketResult:
        """GET /GetStockLive — live trading data for one or all stocks."""
        clean_symbol = stock_symbol.strip().upper() if stock_symbol else ""
        result = await self._get(
            "/GetStockLive", params={"stockSymbol": clean_symbol}
        )
        if not result or not isinstance(result, dict):
            return LiveMarketResult(stocks=[])
        return LiveMarketResult.model_validate(result)

    async def get_stock_snapshot(self, stock_symbol: str) -> StockSnapshot:
        """Return a compact live view for a single stock symbol."""
        live_result = await self.get_stock_live(stock_symbol)
        if not live_result.stocks:
            raise NepseAPIError(f"No live market data found for stock symbol '{stock_symbol.strip().upper()}'.")

        stock = live_result.stocks[0]
        return StockSnapshot(
            stockSymbol=stock.stockSymbol,
            companyName=stock.companyName,
            closingPrice=stock.closingPrice,
            previousClosing=stock.previousClosing,
            differenceRs=stock.differenceRs,
            percentChange=stock.percentChange,
            volume=stock.volume,
            turnover=stock.amount,
            dayHigh=stock.maxPrice,
            dayLow=stock.minPrice,
            openingPrice=stock.openingPrice,
            tradeDate=stock.tradeDate,
            asOfDate=stock.asOfDate,
        )

    async def get_dividend_rights(
        self,
        stock_symbol: str,
        fiscal_year_id: int = 0,
        page_no: int = 1,
        items_per_page: int = 20,
    ) -> PaginatedData[DividendRecord]:
        """GET /GetDividendRights — dividend and rights history for a stock."""
        clean_symbol = stock_symbol.strip().upper()
        result = await self._get(
            "/GetDividendRights",
            params={
                "stockSymbol": clean_symbol,
                "fiscalYearId": fiscal_year_id,
                "pageNo": page_no,
                "itemsPerPage": min(items_per_page, 100),
                "pagePerDisplay": 5,
            },
        )

        if not result or not isinstance(result, dict):
            return PaginatedData[DividendRecord](
                data=[],
                pager=Pager(pageNo=page_no, itemsPerPage=items_per_page, pagePerDisplay=5, totalNextPages=0),
            )

        raw_records = result.get("data") or []
        raw_pager = result.get("pager") or {
            "pageNo": page_no,
            "itemsPerPage": items_per_page,
            "pagePerDisplay": 5,
            "totalNextPages": 0,
        }

        records = [DividendRecord.model_validate(item) for item in raw_records]
        pager = Pager.model_validate(raw_pager)
        return PaginatedData[DividendRecord](data=records, pager=pager)

    async def get_stock_history(
        self,
        stock_symbol: str,
        from_date: str,
        to_date: str,
        page_no: int = 1,
        items_per_page: int = 20,
    ) -> PaginatedData[PriceHistoryRecord]:
        """GET /GetStockHistory — daily OHLC price history for a stock."""
        clean_symbol = stock_symbol.strip().upper()
        result = await self._get(
            "/GetStockHistory",
            params={
                "stockSymbol": clean_symbol,
                "fromDate": from_date,
                "toDate": to_date,
                "pageNo": page_no,
                "itemsPerPage": min(items_per_page, 100),
                "pagePerDisplay": 5,
            },
        )

        if not result or not isinstance(result, dict):
            return PaginatedData[PriceHistoryRecord](
                data=[],
                pager=Pager(pageNo=page_no, itemsPerPage=items_per_page, pagePerDisplay=5, totalNextPages=0),
            )

        raw_records = result.get("data") or []
        raw_pager = result.get("pager") or {
            "pageNo": page_no,
            "itemsPerPage": items_per_page,
            "pagePerDisplay": 5,
            "totalNextPages": 0,
        }

        records = [PriceHistoryRecord.model_validate(item) for item in raw_records]
        pager = Pager.model_validate(raw_pager)
        return PaginatedData[PriceHistoryRecord](data=records, pager=pager)

    async def get_price_history_summary(
        self,
        stock_symbol: str,
        from_date: str,
        to_date: str,
    ) -> PriceHistorySummary:
        """Return compact summary metrics derived from price history."""
        page = await self.get_stock_history(
            stock_symbol=stock_symbol,
            from_date=from_date,
            to_date=to_date,
            items_per_page=100,
        )
        records = page.data
        clean_symbol = stock_symbol.strip().upper()

        if not records:
            raise NepseAPIError(
                f"No price history found for stock symbol '{clean_symbol}' between {from_date} and {to_date}."
            )

        closes = [record.closingPrice for record in records]
        volumes = [record.volume for record in records]
        turnovers = [record.amount for record in records]
        first_close = closes[0]
        last_close = closes[-1]
        absolute_return = round(last_close - first_close, 2)
        percent_return = 0.0
        if first_close != 0:
            percent_return = round((absolute_return / first_close) * 100, 2)

        average_volume = round(sum(volumes) / len(volumes), 2)
        average_turnover = round(sum(turnovers) / len(turnovers), 2)
        day_change = round(records[-1].differenceRs, 2)
        day_change_percent = round(records[-1].percentChange, 2)
        volatility = self._calculate_sample_std_dev(
            [record.percentChange for record in records]
        )
        seven_day_return = self._calculate_period_return(closes, 7)
        thirty_day_return = self._calculate_period_return(closes, 30)
        sma5 = self._calculate_simple_moving_average(closes, 5)
        sma10 = self._calculate_simple_moving_average(closes, 10)
        sma20 = self._calculate_simple_moving_average(closes, 20)
        max_drawdown = self._calculate_max_drawdown(closes)
        volume_trend = self._calculate_volume_trend(volumes)

        return PriceHistorySummary(
            stockSymbol=clean_symbol,
            fromDate=from_date,
            toDate=to_date,
            recordCount=len(records),
            firstClose=first_close,
            lastClose=last_close,
            absoluteReturn=absolute_return,
            percentReturn=percent_return,
            highestClose=max(closes),
            lowestClose=min(closes),
            dayChange=day_change,
            dayChangePercent=day_change_percent,
            sevenDayReturn=seven_day_return,
            thirtyDayReturn=thirty_day_return,
            sma5=sma5,
            sma10=sma10,
            sma20=sma20,
            maxDrawdown=max_drawdown,
            averageVolume=average_volume,
            averageTurnover=average_turnover,
            volatility=volatility,
            volumeTrend=volume_trend,
            trend=self._derive_trend(first_close, last_close, len(records)),
        )

    async def get_top_market_movers(
        self,
        indicator: IndicatorType,
        sector_code: str = "",
        limit: int = 20,
    ) -> list[TopMoverItem]:
        """GET /GetTopMarketMovers — ranked stocks by the chosen indicator."""
        result = await self._get(
            "/GetTopMarketMovers",
            params={
                "indicator": indicator,
                "sectorCode": sector_code.strip(),
                "limit": min(limit, 100),
            },
        )
        if not isinstance(result, list):
            return []
        return [TopMoverItem.model_validate(item) for item in result]

    async def compare_stocks(
        self,
        stock_symbols: list[str],
        metric: CompareMetric,
    ) -> StockComparisonResult:
        """Compare a set of stocks by a fixed metric and return rankings."""
        unique_symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in stock_symbols if symbol.strip()))
        rankings: list[StockComparisonItem] = []
        today = date.today()
        trailing_from_date = (today - timedelta(days=30)).isoformat()
        trailing_to_date = today.isoformat()

        for symbol in unique_symbols:
            if metric == "30d_return":
                summary = await self.get_price_history_summary(
                    stock_symbol=symbol,
                    from_date=trailing_from_date,
                    to_date=trailing_to_date,
                )
                snapshot = await self.get_stock_snapshot(symbol)
                rankings.append(
                    StockComparisonItem(
                        stockSymbol=symbol,
                        companyName=snapshot.companyName,
                        metric=metric,
                        value=summary.thirtyDayReturn
                        if summary.thirtyDayReturn is not None
                        else summary.percentReturn,
                        tradeDate=snapshot.tradeDate,
                        asOfDate=snapshot.asOfDate,
                    )
                )
                continue

            snapshot = await self.get_stock_snapshot(symbol)
            metric_value_map = {
                "closing_price": snapshot.closingPrice,
                "percent_change": snapshot.percentChange,
                "volume": float(snapshot.volume),
                "turnover": snapshot.turnover,
            }
            rankings.append(
                StockComparisonItem(
                    stockSymbol=symbol,
                    companyName=snapshot.companyName,
                    metric=metric,
                    value=metric_value_map[metric],
                    tradeDate=snapshot.tradeDate,
                    asOfDate=snapshot.asOfDate,
                )
            )

        rankings.sort(key=lambda item: item.value, reverse=True)
        return StockComparisonResult(metric=metric, rankings=rankings)

    @staticmethod
    def _calculate_sample_std_dev(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        return round(math.sqrt(variance), 2)

    
    # Calculate the return for a given period
    @staticmethod
    def _calculate_period_return(closes: list[float], period: int) -> float | None:
        if len(closes) < period:
            return None

        if len(closes) == period:
            start_close = closes[0]
        else:
            start_close = closes[-(period + 1)]
        end_close = closes[-1]
        if start_close == 0:
            return None

        return round(((end_close - start_close) / start_close) * 100, 2)

    @staticmethod
    def _calculate_simple_moving_average(
        closes: list[float], window: int
    ) -> float | None:
        if len(closes) < window:
            return None
        return round(sum(closes[-window:]) / window, 2)

    @staticmethod
    def _calculate_max_drawdown(closes: list[float]) -> float:
        if len(closes) < 2:
            return 0.0

        peak = closes[0]
        max_drawdown = 0.0
        for close in closes:
            peak = max(peak, close)
            if peak == 0:
                continue
            drawdown = ((peak - close) / peak) * 100
            max_drawdown = max(max_drawdown, drawdown)
        return round(max_drawdown, 2)

    @staticmethod
    def _calculate_volume_trend(volumes: list[int]) -> str:
        if len(volumes) < 10:
            return "insufficient_data"

        recent_average = sum(volumes[-5:]) / 5
        prior_average = sum(volumes[-10:-5]) / 5
        if prior_average == 0:
            return "insufficient_data"

        change_ratio = ((recent_average - prior_average) / prior_average) * 100
        if change_ratio > 5:
            return "increasing"
        if change_ratio < -5:
            return "decreasing"
        return "stable"

    @staticmethod
    def _derive_trend(first_close: float, last_close: float, record_count: int) -> str:
        if record_count < 2:
            return "insufficient_data"
        if last_close > first_close:
            return "uptrend"
        if last_close < first_close:
            return "downtrend"
        return "sideways"