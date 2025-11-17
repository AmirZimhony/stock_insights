
import json
import logging
import os
from datetime import timedelta

# Pipeline metadata
PIPELINE_VERSION = "1.0.0"
PIPELINE_NAME = "daily_stock_insights"


def load_config(env='dev'):
    """
    Load configuration from config.json
    
    Args:
        env: Environment to load ('dev', 'staging' or 'prod')
        
    Returns:
        dict: Configuration for the specified environment
    """
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        with open(config_path) as f:
            config_data = json.load(f)
        
        env_config = config_data.get(env, {})
        env_config['thresholds'] = config_data.get('thresholds', {})
        
        logging.info(f"Loaded config.json for {env} environment")
        return env_config
    except FileNotFoundError:
        logging.warning("config.json not found, using defaults")
        return {
            "db_name": "stock_test1",
            "source_collection": "stocks_merged_test",
            "target_collection": "daily_stock_summaries_dev",
            "thresholds": {
                "lookback_days": 17,
                "volume_spike_threshold": 2.0,
                "standout_z_threshold": 1.5,
                "min_data_points": 5,
                "trend_up_days": 6,
                "trend_down_days": 4
            }
        }


def get_thresholds(config=None):
    """
    Get thresholds from config
    
    Args:
        config: Config dict (if None, loads dev config)
        
    Returns:
        dict: Thresholds configuration
    """
    if config is None:
        config = load_config('dev')
    return config.get('thresholds', {})

