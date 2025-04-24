import threading
import json
import datetime  # Import the standard datetime module
import os  # Add this import
import sys  # Add this import for the system module
import subprocess  # New import
import requests  # New import
import random
import time
from flask import Flask, render_template, request, redirect, url_for, jsonify  # Add jsonify
import bot as trading_bot
import MetaTrader5 as mt5
# Import the logs module
from logs import get_logs, get_available_components
from strategies import get_available_strategies
from strategy_factory import StrategyFactory

app = Flask(__name__)
# Add min function to Jinja environment
app.jinja_env.globals.update(min=min, max=max)

bot_thread = None
stop_event = threading.Event()

# Define profiles directory
PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'profiles')
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# Create profiles directory if it doesn't exist
if not os.path.exists(PROFILES_DIR):
    os.makedirs(PROFILES_DIR)

# GitHub repo to check
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'your_github_user/market-structure-bot')

# Load configuration from file
def load_config():
    """Load configuration from file"""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

# Save configuration to file
def save_config(config):
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

# Get all available profiles
def get_available_profiles():
    if not os.path.exists(PROFILES_DIR):
        return []
    profiles = [f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith('.json')]
    return sorted(profiles)

# Save current config as a profile
def save_profile(name):
    if not name or '/' in name or '\\' in name:
        return False, "Invalid profile name"
    
    # Load current config
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    except Exception as e:
        return False, f"Error loading current config: {str(e)}"
    
    # Save as profile
    profile_path = os.path.join(PROFILES_DIR, f"{name}.json")
    try:
        with open(profile_path, 'w') as f:
            json.dump(config, f, indent=4)
        return True, "Profile saved successfully"
    except Exception as e:
        return False, f"Error saving profile: {str(e)}"

# Load profile
def load_profile(name):
    profile_path = os.path.join(PROFILES_DIR, f"{name}.json")
    if not os.path.exists(profile_path):
        return False, "Profile not found"
    
    try:
        # Load profile
        with open(profile_path, 'r') as f:
            profile_config = json.load(f)
        
        # Save as current config
        with open(CONFIG_FILE, 'w') as f:
            json.dump(profile_config, f, indent=4)
        
        return True, "Profile loaded successfully"
    except Exception as e:
        return False, f"Error loading profile: {str(e)}"

# Delete profile
def delete_profile(name):
    profile_path = os.path.join(PROFILES_DIR, f"{name}.json")
    if not os.path.exists(profile_path):
        return False, "Profile not found"
    
    try:
        os.remove(profile_path)
        return True, "Profile deleted successfully"
    except Exception as e:
        return False, f"Error deleting profile: {str(e)}"

# Start trading bot in background thread
def start_bot():
    stop_event.clear()
    trading_bot.run(stop_event)

# Get open positions
def get_positions():
    if not mt5.initialize():
        return []
    with open(CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
    symbol = cfg['symbol']
    magic = cfg['magic']
    all_pos = mt5.positions_get() or []
    # filter by symbol & magic
    open_pos = [p for p in all_pos if p.symbol == symbol and p.magic == magic]
    return [format_position(p) for p in open_pos]

# Get trade history with date range parameters
def get_history(from_date=None, to_date=None, limit=None):
    if not mt5.initialize():
        return []
    with open(CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
    magic = cfg['magic']
    
    # Set default date range if not provided (last 30 days)
    if to_date is None:
        to_date = datetime.datetime.now()
    if from_date is None:
        from_date = to_date - datetime.timedelta(days=30)
    
    # Get history for the specified date range
    deals = mt5.history_deals_get(from_date, to_date) or []
    
    # filter by magic
    my_deals = [d for d in deals if getattr(d, 'magic', None) == magic]
    trades = process_history(my_deals)
    
    # Apply limit if specified
    if limit and limit > 0:
        return trades[:limit]
    return trades

# Process history deals into completed trades
def process_history(deals):
    # This is a simplified version - in reality you would need to match
    # opening and closing deals for each position
    trades = []
    for deal in deals:
        trades.append({
            'ticket': deal.ticket,
            'symbol': deal.symbol,
            'type': 'BUY' if deal.type == mt5.DEAL_TYPE_BUY else 'SELL',
            'volume': deal.volume,
            'price_open': deal.price,
            'price_close': deal.price,  # This should be the closing price
            'profit': deal.profit
        })
    return trades

# Get account information
def get_account_info():
    if not mt5.initialize():
        return None
    
    account_info = mt5.account_info()
    if account_info:
        return {
            'balance': account_info.balance,
            'equity': account_info.equity,
            'margin': account_info.margin,
            'margin_free': account_info.margin_free
        }
    return None

# Format position data
def format_position(position):
    position_type = "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL"
    return {
        'ticket': position.ticket,
        'symbol': position.symbol,
        'type': position_type,
        'volume': position.volume,
        'price_open': position.price_open,
        'sl': position.sl,
        'tp': position.tp,
        'profit': position.profit
    }

# Get market structures data
def get_market_structures():
    if not mt5.initialize():
        return None, []
    with open(CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
    symbol = cfg['symbol']
    lookback = int(cfg['lookback'])
    symbol_info = mt5.symbol_info(symbol)
    structures = []
    for name, tf in zip(trading_bot.TIMEFRAME_NAMES, trading_bot.TIMEFRAMES):
        # Fix the NumPy array boolean context issue
        bars = mt5.copy_rates_from_pos(symbol, tf, 0, lookback)
        if bars is None:
            bars = []
        highs, lows = trading_bot.find_pivots(bars)
        direction = trading_bot.check_break(bars, highs, lows, symbol_info)
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            current_price = (tick.bid + tick.ask) / 2
        else:
            current_price = None
        ph, pht = None, None
        if highs:
            idx, price = highs[-1]
            ph = price
            pht = datetime.datetime.fromtimestamp(bars[idx]['time']).strftime('%H:%M:%S')
        pl, plt = None, None
        if lows:
            idx, price = lows[-1]
            pl = price
            plt = datetime.datetime.fromtimestamp(bars[idx]['time']).strftime('%H:%M:%S')
        structures.append({
            'timeframe': name.replace('TIMEFRAME_', ''),
            'market_direction': direction,
            'last_pivot_high': ph,
            'pivot_high_time': pht,
            'last_pivot_low': pl,
            'pivot_low_time': plt,
            'current_price': current_price
        })
    overall = next((s['market_direction'] for s in structures if s['market_direction']), None)
    return overall, structures

def get_latest_github_release():
    """Return (latest_version_str or None)."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return r.json().get("tag_name")
    except Exception:
        return None

@app.route('/update_version')
def update_version():
    """Pull latest code from Git and restart (manual restart may still be needed)."""
    try:
        # Perform git pull in project root
        root = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(['git', 'pull'], cwd=root, capture_output=True, text=True)
        # Optionally stop and restart bot
        stop_event.set()
        return redirect(url_for('dashboard'))
    except Exception:
        return redirect(url_for('dashboard'))

@app.route('/filter_history', methods=['GET', 'POST'])
def filter_history():
    from_date_str = request.form.get('from_date') or request.args.get('from_date')
    to_date_str = request.form.get('to_date') or request.args.get('to_date')
    
    try:
        if from_date_str:
            from_date = datetime.datetime.strptime(from_date_str, '%Y-%m-%d')
        else:
            from_date = datetime.datetime.now() - datetime.timedelta(days=30)
            
        if to_date_str:
            to_date = datetime.datetime.strptime(to_date_str, '%Y-%m-%d')
            # Set to end of day
            to_date = to_date.replace(hour=23, minute=59, second=59)
        else:
            to_date = datetime.datetime.now()
    except ValueError:
        # Handle invalid date format
        from_date = datetime.datetime.now() - datetime.timedelta(days=30)
        to_date = datetime.datetime.now()
    
    # For form submissions, redirect back to dashboard with query params and ensure the anchor is included
    return redirect(url_for('dashboard', 
                          from_date=from_date.strftime('%Y-%m-%d'),
                          to_date=to_date.strftime('%Y-%m-%d')) + '#history')

@app.route('/')
def dashboard():
    config = load_config()
    available_strategies = get_available_strategies()
    
    # Mock data for example purposes
    mock_data = {
        "symbol": config.get("symbol", "Step Index"),
        "timeframe": "H4",
        "status": "running",
        "current_price": 15750.25,
        "market_direction": "bull",
        "overall_direction": "bull",
        "last_pivot_high": 15700.50,
        "last_pivot_low": 15600.75,
        "positions": get_positions(),
        "history": get_history(),
        "logs": get_logs(n=100),
        "account": get_account_info(),
        "market_structures": get_market_structures()[1],
        "profiles": get_available_profiles(),
        "available_strategies": available_strategies,
        "config": config
    }
    
    # Always include stochastic data in the template context
    # with default/empty values when the strategy is not active
    mock_data["stochastic"] = {
        "k_value": None,
        "d_value": None,
        "trend": None,
        "signal": None
    }
    
    # Override with actual values if stochastic is the active strategy
    active_strategy = config.get("active_strategy", "market_structure")
    if active_strategy == "stochastic":
        mock_data["stochastic"] = {
            "k_value": 25.5,
            "d_value": 20.3,
            "trend": "uptrend",
            "signal": "buy"  # Add a signal value
        }
    
    return render_template('dashboard.html', **mock_data)

@app.route('/logs')
def view_logs():
    log_level = request.args.get('level', None)
    log_component = request.args.get('component', None)
    logs = get_logs(n=100, level=log_level, component=log_component)
    log_components = get_available_components()
    
    # If this is just a refresh request, redirect back to dashboard with params
    if request.args.get('refresh'):
        return redirect(url_for('dashboard', level=log_level, component=log_component, _anchor='logs'))
    
    return render_template('dashboard.html',
                          logs=logs,
                          log_level=log_level,
                          log_component=log_component,
                          log_components=log_components)

@app.route('/start')
def start():
    global bot_thread
    if not bot_thread or not bot_thread.is_alive():
        bot_thread = threading.Thread(target=start_bot)
        bot_thread.daemon = True
        bot_thread.start()
    return redirect(url_for('dashboard'))

@app.route('/stop')
def stop():
    stop_event.set()
    return redirect(url_for('dashboard'))

@app.route('/update_config', methods=['POST'])
def update_config():
    config = load_config()
    
    # Update config with form data
    for key, value in request.form.items():
        # Handle boolean values
        if value.lower() in ['true', 'false']:
            config[key] = value.lower() == 'true'
        # Handle numeric values
        elif value.replace('.', '', 1).isdigit():
            if '.' in value:
                config[key] = float(value)
            else:
                config[key] = int(value)
        # Handle everything else as strings
        else:
            config[key] = value
    
    save_config(config)
    return redirect('/')

@app.route('/save_profile', methods=['POST'])
def save_profile_route():
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Profile name is required'})
    
    success, message = save_profile(name)
    return jsonify({'success': success, 'message': message})

@app.route('/load_profile')
def load_profile_route():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Profile name is required'})
    
    success, message = load_profile(name)
    if success:
        # Optionally stop the bot so new config is used on next start
        global bot_thread
        stop_event.set()
        # Wait for bot to stop
        if bot_thread and bot_thread.is_alive():
            bot_thread.join(timeout=2)
        bot_thread = None
        # Return reload instruction to frontend
        return jsonify({'success': True, 'message': message, 'reload': True})
    else:
        return jsonify({'success': False, 'message': message})

@app.route('/delete_profile')
def delete_profile_route():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Profile name is required'})
    
    success, message = delete_profile(name)
    return jsonify({'success': success, 'message': message})

@app.route('/get_config')
def get_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        return jsonify({'success': True, 'config': cfg})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# Chart view route
@app.route('/chart/<symbol>')
def chart_view(symbol):
    """Render the chart view for a specific symbol"""
    return render_template('chart_view.html', symbol=symbol)

# API endpoint for candle data
@app.route('/api/candles')
def get_candles():
    """API endpoint to get candlestick data for a specific symbol and timeframe"""
    symbol = request.args.get('symbol', '')
    timeframe = request.args.get('timeframe', '1h')
    
    try:
        # In a real implementation, you would fetch data from your trading platform
        # or market data provider here. This is just demo data.
        
        # For this example, I'll generate some random candle data
        candles = generate_demo_candles(timeframe)
        
        # Get pivot points if available
        pivots = get_pivot_points(symbol, timeframe)
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'timeframe': timeframe,
            'candles': candles,
            'pivots': pivots
        })
    except Exception as e:
        app.logger.error(f"Error getting candle data: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Error getting candle data: {str(e)}"
        })

# API endpoint for indicators
@app.route('/api/indicator')
def get_indicator():
    """API endpoint to get indicator data"""
    symbol = request.args.get('symbol', '')
    indicator_type = request.args.get('type', '')
    period = int(request.args.get('period', 14))
    timeframe = request.args.get('timeframe', '1h')
    
    try:
        # In a real implementation, you would calculate indicators based on
        # actual price data. This is just demo data.
        
        # For this example, I'll generate some random indicator values
        values = generate_demo_indicator(timeframe, indicator_type, period)
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'type': indicator_type,
            'period': period,
            'values': values
        })
    except Exception as e:
        app.logger.error(f"Error getting indicator data: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Error getting indicator data: {str(e)}"
        })

# Helper function to generate demo candle data
def generate_demo_candles(timeframe):
    """Generate demo candle data for testing"""
    candles = []
    now = int(time.time())
    
    # Determine candlestick interval based on timeframe
    if timeframe.endswith('h'):
        interval = 3600 * int(timeframe[:-1])
    elif timeframe.endswith('d'):
        interval = 86400 * int(timeframe[:-1])
    elif timeframe.endswith('w'):
        interval = 604800 * int(timeframe[:-1])
    elif timeframe.endswith('m'):
        interval = 2592000 * int(timeframe[:-1])
    else:
        interval = 3600  # Default to 1 hour
    
    # Start price around 100
    base_price = 100
    price = base_price
    
    # Generate 100 candles
    for i in range(100):
        # Calculate timestamp for this candle
        timestamp = now - (99 - i) * interval
        
        # Generate random price movements
        price_change = random.uniform(-2, 2)
        price += price_change
        
        open_price = price
        close_price = price + random.uniform(-1, 1)
        high_price = max(open_price, close_price) + random.uniform(0, 1)
        low_price = min(open_price, close_price) - random.uniform(0, 1)
        
        candles.append({
            'time': timestamp,
            'open': round(open_price, 2),
            'high': round(high_price, 2),
            'low': round(low_price, 2),
            'close': round(close_price, 2)
        })
    
    return candles

# Helper function to generate demo indicator values
def generate_demo_indicator(timeframe, indicator_type, period):
    """Generate demo indicator values for testing"""
    values = []
    now = int(time.time())
    
    # Determine interval based on timeframe
    if timeframe.endswith('h'):
        interval = 3600 * int(timeframe[:-1])
    elif timeframe.endswith('d'):
        interval = 86400 * int(timeframe[:-1])
    elif timeframe.endswith('w'):
        interval = 604800 * int(timeframe[:-1])
    elif timeframe.endswith('m'):
        interval = 2592000 * int(timeframe[:-1])
    else:
        interval = 3600  # Default to 1 hour
    
    # Start value around 100
    base_value = 100
    value = base_value
    
    # Generate 100 values
    for i in range(100):
        # Calculate timestamp for this value
        timestamp = now - (99 - i) * interval
        
        # Generate random value movements (smoother for indicators)
        if indicator_type == 'sma':
            value = base_value + random.uniform(-5, 5)
        elif indicator_type == 'ema':
            value = base_value + random.uniform(-3, 3) + (i * 0.05)
        else:
            value = base_value + random.uniform(-4, 4)
        
        values.append({
            'time': timestamp,
            'value': round(value, 2)
        })
    
    return values

# Helper function to get pivot points
def get_pivot_points(symbol, timeframe):
    """Get pivot points for a symbol and timeframe"""
    # In a real implementation, you would fetch actual pivot points
    # from your market structure analysis. This is just demo data.
    
    # Generate a few random pivot highs and lows
    now = int(time.time())
    
    # Determine interval based on timeframe
    if timeframe.endswith('h'):
        interval = 3600 * int(timeframe[:-1])
    elif timeframe.endswith('d'):
        interval = 86400 * int(timeframe[:-1])
    elif timeframe.endswith('w'):
        interval = 604800 * int(timeframe[:-1])
    elif timeframe.endswith('m'):
        interval = 2592000 * int(timeframe[:-1])
    else:
        interval = 3600  # Default to 1 hour
    
    base_price = 100
    
    # Generate some pivot highs
    pivot_highs = []
    for i in range(1, 6):  # 5 pivot highs
        timestamp = now - (90 - i * 15) * interval  # Spread them out
        value = base_price + random.uniform(5, 10)  # Higher than base price
        pivot_highs.append({
            'time': timestamp,
            'value': round(value, 2)
        })
    
    # Generate some pivot lows
    pivot_lows = []
    for i in range(1, 6):  # 5 pivot lows
        timestamp = now - (82 - i * 15) * interval  # Offset from highs
        value = base_price - random.uniform(3, 8)  # Lower than base price
        pivot_lows.append({
            'time': timestamp,
            'value': round(value, 2)
        })
    
    return {
        'highs': pivot_highs,
        'lows': pivot_lows
    }

if __name__ == '__main__':
    # When running as a service, bind to all interfaces (0.0.0.0)
    # and don't use debug mode
    is_service = not hasattr(sys, 'getwindowsversion')
    
    # Get the port from an environment variable if specified, otherwise use 5000
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    
    # Get the host from an environment variable if specified, otherwise bind to all interfaces
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    
    # Don't use debug mode when running as a service
    debug_mode = False if is_service else True
    
    app.run(host=host, port=port, debug=debug_mode)