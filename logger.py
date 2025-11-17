"""
Logging configuration module.
Optimized for containers/Airflow (stderr) with optional file logging.
"""
import logging
import os
import sys
import warnings
from datetime import datetime


def setup_logging(date=None, env=None):
    """
    Setup logging configuration.
    
    - Primary: stderr (standard for containerized apps, captured by Airflow/Docker)
    - Optional: file logging if LOG_DIR is provided and writable
    - Gracefully falls back to stderr-only if file logging fails
    
    Args:
        date: Date string (DD-MM-YYYY) to include in log filename
        env: Environment name (dev/prod) to include in log filename
    """
    # Filter out the annoying scipy RuntimeWarning about precision loss in zscore
    warnings.filterwarnings('ignore', category=RuntimeWarning, 
                          message='.*Precision loss occurred in moment calculation.*')
    
    log_level = getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper())

    # Get root logger and clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    
    # Use stderr for logging (standard for containerized apps, works in all environments)
    # Airflow/Docker captures stderr more reliably than stdout
    handlers = [logging.StreamHandler(sys.stderr)]

    # Optional file logging - only if LOG_DIR is explicitly set (no default)
    log_dir = os.getenv('LOG_DIR')
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
            # Fall back to stdout/stderr only (common in containers)
            pass

    # Configure format for all handlers
    formatter = logging.Formatter('%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s')
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.setLevel(log_level)
        root_logger.addHandler(handler)
    
    # Set root logger level
    root_logger.setLevel(log_level)
    
    if logfile:
        logging.info(f"Logging to file: {logfile}")

