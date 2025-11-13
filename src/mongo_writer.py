"""
MongoDB writer - Upsert daily summaries with validation
"""
import logging
from datetime import datetime
from typing import Dict, List
import pandas as pd
from pymongo import ASCENDING, DESCENDING
from config import PIPELINE_VERSION, PIPELINE_NAME
from src.models import DailySummary, ComparisonData, AnalysisMeta
from src.utils import get_mongo_client


def upsert_summaries(
    df: pd.DataFrame,
    db_name: str,
    target_collection: str
) -> Dict:
    """
    Upsert daily summaries to MongoDB
    
    Args:
        df: DataFrame with calculated summaries
        db_name: Database name
        target_collection: Target collection name
        
    Returns:
        Dictionary with operation results
    """
    if df.empty:
        logging.warning("Empty DataFrame provided to upsert_summaries")
        return {'upserted': 0, 'errors': 0}
    
    # Filter to only latest date
    latest_date = df['date'].max()
    df_latest = df[df['date'] == latest_date].copy()
    
    logging.info(f"Upserting {len(df_latest)} summaries to {db_name}.{target_collection}")
    
    # Connect to MongoDB
    client = get_mongo_client()
    db = client[db_name]
    collection = db[target_collection]
    
    # Create indexes if they don't exist
    _create_indexes(collection)
    
    # Convert DataFrame rows to documents
    documents = _prepare_documents(df_latest)
    
    # Upsert documents
    result = _upsert_documents(collection, documents)
    
    client.close()
    
    logging.info(f"Upserted {result['upserted']} documents, {result['errors']} errors")
    
    return result


def _create_indexes(collection):
    """Create required indexes if they don't exist"""
    try:
        # Check existing indexes
        existing_indexes = collection.index_information()
        
        # Index 1: {exchange:1, exchange_sector:1, date:-1, ticker:1}
        if 'exchange_1_exchange_sector_1_date_-1_ticker_1' not in existing_indexes:
            collection.create_index([
                ('exchange', ASCENDING),
                ('exchange_sector', ASCENDING),
                ('date', DESCENDING),
                ('ticker', ASCENDING)
            ], name='exchange_1_exchange_sector_1_date_-1_ticker_1')
            logging.info("Created index: exchange_1_exchange_sector_1_date_-1_ticker_1")
        
        # Index 2: {ticker:1, exchange:1, date:-1}
        if 'ticker_1_exchange_1_date_-1' not in existing_indexes:
            collection.create_index([
                ('ticker', ASCENDING),
                ('exchange', ASCENDING),
                ('date', DESCENDING)
            ], name='ticker_1_exchange_1_date_-1')
            logging.info("Created index: ticker_1_exchange_1_date_-1")
        
        # Index 3: {exchange:1, date:-1}
        if 'exchange_1_date_-1' not in existing_indexes:
            collection.create_index([
                ('exchange', ASCENDING),
                ('date', DESCENDING)
            ], name='exchange_1_date_-1')
            logging.info("Created index: exchange_1_date_-1")
        
    except Exception as e:
        logging.warning(f"Error creating indexes: {e}")


def _prepare_documents(df: pd.DataFrame) -> List[Dict]:
    """
    Prepare documents from DataFrame
    
    Args:
        df: DataFrame with summary data
        
    Returns:
        List of validated documents
    """
    documents = []
    
    for _, row in df.iterrows():
        try:
            # Create comparison data
            comparison = ComparisonData(
                prev_date=row.get('comparison_prev_date'),
                delta_pct_change=row.get('comparison_delta_pct_change'),
                delta_vol_ratio=row.get('comparison_delta_vol_ratio'),
                delta_consistency=row.get('comparison_delta_consistency'),
                prev_exists=row.get('comparison_prev_exists', False)
            )
            
            # Create analysis metadata
            analysis_meta = AnalysisMeta(
                pipeline_version=PIPELINE_VERSION,
                generated_by=PIPELINE_NAME,
                computed_at=datetime.utcnow()
            )
            
            # Create daily summary
            summary = DailySummary(
                ticker=row['ticker'],
                name=row.get('company') or row.get('name'),
                exchange=row['exchange'],
                date=row['date'],
                last_price=row.get('last_price') or row.get('price'),
                prev_close=row.get('prev_close'),
                pct_change=row['pct_change'],
                volume=row['volume'],
                vol_ratio=row.get('vol_ratio'),
                vol_z=row.get('vol_z'),
                vol_spike_flag=row.get('vol_spike_flag', False),
                new_in_market=row.get('new_in_market', False),
                sector=row.get('sector'),
                industry=row.get('industry'),
                country=row.get('country'),
                exchange_sector=row.get('exchange_sector'),
                exchange_industry=row.get('exchange_industry'),
                exchange_country=row.get('exchange_country'),
                exchange_return=row.get('exchange_return'),
                sector_return=row.get('sector_return'),
                industry_return=row.get('industry_return'),
                country_return=row.get('country_return'),
                robust_abs=row.get('robust_abs'),
                robust_rel_z=row.get('robust_rel_z'),
                is_robust_on_bad_day=row.get('is_robust_on_bad_day', False),
                standout_z=row.get('standout_z'),
                standout_flag=row.get('standout_flag', False),
                consistency_score=row.get('consistency_score'),
                num_of_rising_days=int(row['num_of_rising_days']),
                accumulated_change=row['accumulated_change'],
                trend_label=row.get('trend_label'),
                market_cap=row.get('market_cap'),
                pe_ratio=row.get('pe_ratio'),
                comparison=comparison,
                confidence=row.get('confidence', 1.0),
                bootstrap_source=row.get('bootstrap_source'),
                analysis_meta=analysis_meta
            )
            
            # Convert to dictionary
            doc = summary.to_mongo_dict()
            documents.append(doc)
            
        except Exception as e:
            logging.error(f"Error preparing document for {row.get('ticker')}: {e}")
            continue
    
    return documents


def _upsert_documents(collection, documents: List[Dict]) -> Dict:
    """
    Upsert documents to MongoDB
    
    Args:
        collection: MongoDB collection
        documents: List of documents to upsert
        
    Returns:
        Dictionary with upsert results
    """
    upserted_count = 0
    error_count = 0
    
    for doc in documents:
        try:
            # Upsert by ticker, exchange, and date
            filter_query = {
                'ticker': doc['ticker'],
                'exchange': doc['exchange'],
                'date': doc['date']
            }
            
            result = collection.update_one(
                filter_query,
                {'$set': doc},
                upsert=True
            )
            
            if result.upserted_id or result.modified_count > 0:
                upserted_count += 1
                
        except Exception as e:
            logging.error(f"Error upserting document for {doc.get('ticker')}: {e}")
            error_count += 1
    
    return {
        'upserted': upserted_count,
        'errors': error_count,
        'total': len(documents)
    }

