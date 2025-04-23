import logging
import os
import time
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Create logs directory if it doesn't exist
logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Configure the root logger
logger = logging.getLogger('market_structure')
logger.setLevel(logging.DEBUG)

# Create log file with timestamp
log_filename = os.path.join(logs_dir, f'market_structure_{datetime.now().strftime("%Y%m%d")}.log')

# Add rotating file handler
file_handler = RotatingFileHandler(
    log_filename, 
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
file_handler.setLevel(logging.DEBUG)

# Add console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

def get_logger(name):
    """Get a logger with the specified name."""
    return logging.getLogger(f'market_structure.{name}')

def get_logs(n=100, level=None, component=None):
    """
    Get the last n log entries.
    
    Args:
        n (int): Number of log entries to retrieve
        level (str, optional): Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        component (str, optional): Filter by component (e.g., 'app', 'bot')
        
    Returns:
        list: List of log entries as dictionaries
    """
    logs = []
    
    try:
        with open(log_filename, 'r') as f:
            lines = f.readlines()
            
        # Process lines in reverse order (newest first)
        for line in reversed(lines):
            # Skip empty lines
            if not line.strip():
                continue
                
            try:
                # Parse log line
                parts = line.split(' - ', 3)
                if len(parts) < 4:
                    continue
                    
                timestamp = parts[0]
                log_component = parts[1]
                log_level = parts[2]
                message = parts[3].strip()
                
                # Apply filters
                if level and level != log_level:
                    continue
                if component and component not in log_component:
                    continue
                
                logs.append({
                    'timestamp': timestamp,
                    'component': log_component,
                    'level': log_level,
                    'message': message,
                    'color': get_level_color(log_level)
                })
                
                # Stop when we have enough logs
                if len(logs) >= n:
                    break
                    
            except Exception as e:
                # Skip lines that can't be parsed
                continue
    except FileNotFoundError:
        logs.append({
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'component': 'market_structure.logs',
            'level': 'WARNING',
            'message': 'No log file found',
            'color': get_level_color('WARNING')
        })
    
    return logs

def get_level_color(level):
    """Get CSS color class for a log level."""
    level_colors = {
        'DEBUG': 'text-slate-500',
        'INFO': 'text-blue-600',
        'WARNING': 'text-yellow-600',
        'ERROR': 'text-red-600',
        'CRITICAL': 'text-purple-600'
    }
    return level_colors.get(level, 'text-slate-500')

def get_available_components():
    """Get list of logging components found in the logs."""
    components = set()
    
    try:
        with open(log_filename, 'r') as f:
            for line in f:
                parts = line.split(' - ', 3)
                if len(parts) >= 4:
                    component = parts[1]
                    components.add(component)
    except FileNotFoundError:
        pass
    
    return sorted(list(components))

def clear_logs():
    """Clear the log file (for debugging purposes)."""
    try:
        open(log_filename, 'w').close()
        return True
    except Exception:
        return False
