"""
Pydantic models for data validation
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class StockDataInput(BaseModel):
    """Input data from stocks_merged collection"""
    ticker: str
    company: Optional[str] = None
    price: float
    change: float
    num_of_rising_days: int
    accumulated_change: float
    exchange: str
    volume: float
    sector: Optional[str] = None
    market_cap: Optional[float] = None
    country: Optional[str] = None
    pe_ratio: Optional[float] = None
    serial_number: Optional[int] = None
    date: datetime
    industry: Optional[str] = None


class ComparisonData(BaseModel):
    """Comparison data from previous day"""
    prev_date: Optional[datetime] = None
    delta_pct_change: Optional[float] = None
    delta_vol_ratio: Optional[float] = None
    delta_consistency: Optional[float] = None
    prev_exists: bool = False


class AnalysisMeta(BaseModel):
    """Pipeline metadata"""
    pipeline_version: str
    generated_by: str
    computed_at: datetime


class DailySummary(BaseModel):
    """Complete daily summary document for MongoDB"""
    # Required fields
    ticker: str
    name: Optional[str] = None
    exchange: str
    date: datetime
    
    # Price data
    last_price: float
    prev_close: Optional[float] = None
    pct_change: float
    
    # Volume data
    volume: float
    vol_ratio: Optional[float] = None
    vol_z: Optional[float] = None
    vol_spike_flag: bool = False
    new_in_market: bool = False
    
    # Sector/Industry/Country
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    exchange_sector: Optional[str] = None
    exchange_industry: Optional[str] = None
    exchange_country: Optional[str] = None
    
    # Exchange context
    exchange_return: Optional[float] = None
    sector_return: Optional[float] = None
    industry_return: Optional[float] = None
    country_return: Optional[float] = None
    
    # Robustness metrics
    robust_abs: Optional[float] = None
    robust_rel_z: Optional[float] = None
    is_robust_on_bad_day: bool = False
    
    # Standout metrics
    standout_z: Optional[float] = None
    standout_flag: bool = False
    
    # Consistency metrics
    consistency_score: Optional[float] = None
    num_of_rising_days: int
    accumulated_change: float
    trend_label: Optional[str] = None
    
    # Additional fields
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    
    # Comparison to previous day
    comparison: ComparisonData
    
    # Confidence and bootstrap
    confidence: float = 1.0
    bootstrap_source: Optional[str] = None
    
    # Metadata
    analysis_meta: AnalysisMeta
    
    @field_validator('trend_label')
    @classmethod
    def validate_trend_label(cls, v):
        if v is not None and v not in ['up', 'down', 'sideways']:
            raise ValueError('trend_label must be one of: up, down, sideways')
        return v
    
    def to_mongo_dict(self):
        """Convert to MongoDB-compatible dictionary"""
        data = self.model_dump()
        # Convert nested models to dicts
        if isinstance(data.get('comparison'), dict):
            pass  # Already a dict
        if isinstance(data.get('analysis_meta'), dict):
            pass  # Already a dict
        return data

