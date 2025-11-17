"""
MongoDB writer - Upsert daily summaries with validation
"""
import logging
import time
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
    # TODO: Remove most timing logs before pushing - these are for performance debugging only
    start_time = time.time()
    
    if df.empty:
        logging.warning("Empty DataFrame provided to upsert_summaries")
        return {'upserted': 0, 'errors': 0}
    
    # Filter to only latest date
    stage_start = time.time()
    latest_date = df['date'].max()
    df_latest = df[df['date'] == latest_date].copy()
    logging.info(f"Filtered to latest date: {time.time() - stage_start:.2f}s - {len(df_latest)} records")
    
    logging.info(f"Upserting {len(df_latest)} summaries to {db_name}.{target_collection}")
    
    # Connect to MongoDB
    stage_start = time.time()
    client = get_mongo_client()
    db = client[db_name]
    collection = db[target_collection]
    logging.info(f"MongoDB connection: {time.time() - stage_start:.2f}s")
    
    # Create indexes if they don't exist
    stage_start = time.time()
    _create_indexes(collection)
    logging.info(f"Index creation/check: {time.time() - stage_start:.2f}s")
    
    # Convert DataFrame rows to documents
    stage_start = time.time()
    documents = _prepare_documents(df_latest)
    logging.info(f"Document preparation: {time.time() - stage_start:.2f}s - {len(documents)} documents")
    
    # Insert documents
    stage_start = time.time()
    result = _upsert_documents(collection, documents)
    logging.info(f"Document insert: {time.time() - stage_start:.2f}s")
    
    client.close()
    
    total_time = time.time() - start_time
    logging.info(f"Upserted {result['upserted']} documents, {result['errors']} errors")
    logging.info(f"Total upsert_summaries time: {total_time:.2f}s ({total_time/60:.2f} minutes)")
    
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
    # TODO: Remove timing logs before pushing - for performance debugging only
    start_time = time.time()
    documents = []
    total_rows = len(df)
    progress_interval = max(1000, total_rows // 10)  # Log every 1000 or 10% of total
    
    for idx, (_, row) in enumerate(df.iterrows(), 1):
        if idx % progress_interval == 0 or idx == total_rows:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            logging.info(f"Preparing documents: {idx}/{total_rows} ({idx*100//total_rows}%) - {elapsed:.2f}s - {rate:.0f} docs/s")
        try:
            # Create comparison data
            # Convert prev_date from DD-MM-YYYY string to datetime if it's a string
            prev_date_value = row.get('comparison_prev_date')
            if prev_date_value and isinstance(prev_date_value, str):
                try:
                    prev_date_value = datetime.strptime(prev_date_value, '%d-%m-%Y')
                except ValueError:
                    prev_date_value = None  # Invalid date string, set to None
            
            comparison = ComparisonData(
                prev_date=prev_date_value,
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
    
    total_time = time.time() - start_time
    logging.info(f"Document preparation complete: {len(documents)} documents in {total_time:.2f}s ({total_time/60:.2f} minutes) - {len(documents)/total_time:.0f} docs/s")
    
    return documents


def _upsert_documents(collection, documents: List[Dict]) -> Dict:
    """
    Insert documents to MongoDB using bulk insert with batching
    
    Args:
        collection: MongoDB collection
        documents: List of documents to insert
        
    Returns:
        Dictionary with operation results
    """
    # TODO: Remove timing logs before pushing - for performance debugging only
    start_time = time.time()
    total_docs = len(documents)
    batch_size = 1500  # Use 1.5k batch size (safe between 1k-2k)
    inserted_count = 0
    error_count = 0
    
    # Process documents in batches
    for i in range(0, total_docs, batch_size):
        batch = documents[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (total_docs + batch_size - 1) // batch_size
        
        try:
            # Use insert_many for bulk insert (much faster than individual inserts)
            result = collection.insert_many(batch, ordered=False)
            batch_inserted = len(result.inserted_ids)
            inserted_count += batch_inserted
            logging.info(f"Batch {batch_num}/{total_batches}: Inserted {batch_inserted}/{len(batch)} documents")
        except Exception as e:
            # If bulk insert fails, it might be due to duplicates
            # Log the error but continue with next batch
            logging.error(f"Error in bulk insert batch {batch_num}/{total_batches}: {e}")
            error_count += len(batch)
    
    total_time = time.time() - start_time
    avg_time_per_doc = total_time / total_docs if total_docs > 0 else 0
    logging.info(f"Document insert complete: {inserted_count} inserted, {error_count} errors in {total_time:.2f}s ({total_time/60:.2f} minutes)")
    logging.info(f"Average time per document: {avg_time_per_doc*1000:.1f}ms - Rate: {total_docs/total_time:.0f} docs/s")
    
    return {
        'upserted': inserted_count,  # Keep same return format for compatibility
        'errors': error_count,
        'total': len(documents)
    }

