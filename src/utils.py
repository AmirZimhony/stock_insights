"""
Utility functions shared across modules
"""
import os
import argparse
import logging
from pymongo import MongoClient
from config import load_config


def get_mongo_client():
    """Get MongoDB client from environment"""
    mongo_uri = os.getenv('db_url', 'mongodb://localhost:27017/')
    return MongoClient(mongo_uri)


def parse_args():
    """
    Parse command-line arguments
    
    Returns:
        tuple: (args, db_name, source_collection, target_collection, thresholds)
    """
    parser = argparse.ArgumentParser(
        description='Daily Stock Insights Pipeline - Generate daily stock summaries with exchange context'
    )
    parser.add_argument(
        '--date',
        required=True,
        help='Target date in DD-MM-YYYY format'
    )
    parser.add_argument(
        '--prev-date',
        required=True,
        help='Previous date for comparisons in DD-MM-YYYY format'
    )
    parser.add_argument(
        '--env',
        default='dev',
        choices=['dev', 'prod', 'staging'],
        help='Environment: dev, staging or prod (default: dev)'
    )
    parser.add_argument(
        '--db-name',
        help='Database name (overrides config.json)'
    )
    parser.add_argument(
        '--source-collection',
        help='Source collection name (overrides config.json)'
    )
    parser.add_argument(
        '--target-collection',
        help='Target collection name (overrides config.json)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.env)
    
    # Override with command-line arguments if provided
    db_name = args.db_name or config['db_name']
    source_collection = args.source_collection or config['source_collection']
    target_collection = args.target_collection or config['target_collection']
    thresholds = config.get('thresholds', {})
    
    return args, db_name, source_collection, target_collection, thresholds

