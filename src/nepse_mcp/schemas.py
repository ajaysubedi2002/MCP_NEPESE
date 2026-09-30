from typing import Any, Generic, List, Optional, TypeVar, Literal

from pydantic import BaseModel, Field, field_validator


T = TypeVar("T")


class JevDecisionRequest(BaseModel):
    state: Any
    questions: dict[str, Any]
    model: str = "jev-latest"

    @field_validator("questions")
    @classmethod
    def require_questions(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("questions must contain at least one Jev question")
        return value


class Pager(BaseModel):
    """Pagination metadata returned by the NEPSE API."""
    pageNo: int
    itemsPerPage: int
    pagePerDisplay: int
    totalNextPages: int


class Company(BaseModel):
    companyId: int
    companyName: str
    stockSymbol: str
    sectorId: int
    sectorName: Optional[str] = None


class BaseMarketItem(BaseModel):
    """Base model for shared market data fields to keep things DRY."""
    stockSymbol: str
    companyName: str
    noOfTransactions: int = Field(description="Total number of trades executed.")
    maxPrice: float = Field(description="Highest traded price of the day.")
    minPrice: float = Field(description="Lowest traded price of the day.")
    openingPrice: float
    closingPrice: float = Field(description="Last Traded Price (LTP) or final close.")
    amount: float = Field(description="Total turnover value in Nepalese Rupees (NPR).")
    previousClosing: float
    differenceRs: float = Field(description="Absolute price change in NPR.")
    percentChange: float = Field(description="Percentage change from previous close.")
    volume: int = Field(description="Total number of shares traded.")
    ltv: float = Field(default=0.0, description="Last Traded Volume.")
    asOfDate: str
    asOfDateString: Optional[str] = None
    tradeDate: str
    dataType: Optional[str] = None


class StockLiveItem(BaseMarketItem):
    """Represents a single stock's live trading data."""
    pass


class TopMoverItem(BaseMarketItem):
    """Represents a top moving stock (gainer, turnover, or volume)."""
    pass


class MarketSummary(BaseModel):
    totalAmount: float = Field(description="Total market turnover in NPR.")
    totalShares: int = Field(description="Total market volume (shares traded).")
    totalTxns: int = Field(description="Total number of transactions across the market.")


class LiveMarketResult(BaseModel):
    stocks: List[StockLiveItem]
    summary: Optional[MarketSummary] = None


class DividendRecord(BaseModel):
    sn: int
    companyName: str
    stockSymbol: str
    bonus: float = Field(default=0.0, description="Bonus share percentage.")
    cash: float = Field(default=0.0, description="Cash dividend percentage.")
    totalDividend: float = Field(default=0.0, description="Total dividend percentage.")
    bookClosureDateAD: Optional[str] = None
    bookClosureDateBS: Optional[str] = None
    fiscalYearAD: Optional[str] = None
    fiscalYearBS: Optional[str] = Field(None, description="Fiscal year in Bikram Sambat (e.g., '2079/80').")
    rightShare: Optional[str] = Field(None, description="Rights share issuance ratio if applicable.")
    rightBookCloseDateAD: Optional[str] = None
    rightBookCloseDateBS: Optional[str] = None

    @field_validator("bonus", "cash", "totalDividend", mode="before")
    @classmethod
    def parse_str_float(cls, value: object) -> float:
        """Safely parse floats, handling dirty API data like commas, hyphens, or 'N/A'."""
        if isinstance(value, str):
            clean_val = value.strip().replace(",", "")
            if clean_val in ("", "-", "N/A", "null"):
                return 0.0
            try:
                return float(clean_val)
            except ValueError:
                return 0.0
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0


class PriceHistoryRecord(BaseModel):
    sn: int
    tradeDate: str
    tradeDateString: Optional[str] = None
    maxPrice: float
    minPrice: float
    closingPrice: float
    noOfTransactions: int
    volume: int
    amount: float = Field(description="Turnover amount in NPR.")
    previousClosing: float
    differenceRs: float
    percentChange: float


IndicatorType = Literal["gainers", "turnover", "sharestraded"]
CompareMetric = Literal[
    "closing_price", "percent_change", "volume", "turnover", "30d_return"
]
TrendLabel = Literal["uptrend", "downtrend", "sideways", "insufficient_data"]
VolumeTrendLabel = Literal["increasing", "decreasing", "stable", "insufficient_data"]


class PaginatedData(BaseModel, Generic[T]):
    """Wraps a page of data with pagination metadata."""
    data: List[T]
    pager: Pager


class CompanySearchHit(BaseModel):
    companyId: int
    companyName: str
    stockSymbol: str
    sectorId: int
    sectorName: Optional[str] = None
    matchType: Literal["exact_symbol", "prefix_symbol", "name_match"]


class StockSnapshot(BaseModel):
    stockSymbol: str
    companyName: str
    closingPrice: float
    previousClosing: float
    differenceRs: float
    percentChange: float
    volume: int
    turnover: float
    dayHigh: float
    dayLow: float
    openingPrice: float
    tradeDate: str
    asOfDate: str


class CompactLiveStock(BaseModel):
    """Normalized live/mover stock fields without upstream noise."""

    stockSymbol: str
    companyName: str
    closingPrice: float
    previousClosing: float
    dayChange: float
    percentChange: float
    volume: int
    turnover: float
    dayHigh: float
    dayLow: float
    openingPrice: float
    noOfTransactions: int
    tradeDate: str
    asOfDate: str


class CompactMarketSummary(BaseModel):
    totalTurnover: float
    totalShares: int
    totalTxns: int


class CompactLiveMarketResult(BaseModel):
    stocks: List[CompactLiveStock]
    summary: Optional[CompactMarketSummary] = None


class CompactPriceHistoryRecord(BaseModel):
    tradeDate: str
    dayHigh: float
    dayLow: float
    closingPrice: float
    previousClosing: float
    dayChange: float
    percentChange: float
    volume: int
    turnover: float
    noOfTransactions: int


class CompactDividendRecord(BaseModel):
    companyName: str
    stockSymbol: str
    bonus: float
    cash: float
    totalDividend: float
    bookClosureDateAD: Optional[str] = None
    fiscalYearAD: Optional[str] = None
    fiscalYearBS: Optional[str] = None
    rightShare: Optional[str] = None
    rightBookCloseDateAD: Optional[str] = None


class PriceHistorySummary(BaseModel):
    stockSymbol: str
    fromDate: str
    toDate: str
    recordCount: int
    firstClose: float
    lastClose: float
    absoluteReturn: float
    percentReturn: float
    highestClose: float
    lowestClose: float
    dayChange: float
    dayChangePercent: float
    sevenDayReturn: float | None = None
    thirtyDayReturn: float | None = None
    sma5: float | None = None
    sma10: float | None = None
    sma20: float | None = None
    maxDrawdown: float
    averageVolume: float
    averageTurnover: float
    volatility: float
    volumeTrend: VolumeTrendLabel
    trend: TrendLabel


class StockComparisonItem(BaseModel):
    stockSymbol: str
    companyName: str
    metric: CompareMetric
    value: float
    tradeDate: Optional[str] = None
    asOfDate: Optional[str] = None


class StockComparisonResult(BaseModel):
    metric: CompareMetric
    rankings: List[StockComparisonItem]