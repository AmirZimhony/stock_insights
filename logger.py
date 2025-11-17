"""
Logging configuration module.
Optimized for containers/Airflow (stdout) with optional file logging.
"""
import logging
import os
import sys
from datetime import datetime


def setup_logging(date=None, env=None):
    """
    Setup logging configuration.
    
    - Primary: stdout (captured by Airflow/Docker)
    - Optional: file logging if LOG_DIR is provided and writable
    - Gracefully falls back to stdout-only if file logging fails
    
    Args:
        date: Date string (YYYY-MM-DD) to include in log filename
        env: Environment name (dev/prod) to include in log filename
    """
    log_level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper())

    # Primary handler: stdout for Airflow/Docker
    handlers = [logging.StreamHandler(sys.stdout)]

    # Optional file logging
    log_dir = os.getenv('LOG_DIR', 'logs')
    logfile = None
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            
            # Create filename with timestamp, date, and environment
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            date_str = date.replace('-', '') if date else ''
            env_str = f"_{env}" if env else ''
            logfile = os.path.join(
                log_dir, 
                f'stock_insights_{timestamp}{env_str}_{date_str}.log'
            )
            handlers.append(logging.FileHandler(logfile))
        except Exception:
            # Fall back to stdout only (common in containers)
            pass

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s',
        handlers=handlers,
        force=True  # Override any existing configuration
    )
    
    if logfile:
        logging.info(f"Logging to file: {logfile}")

