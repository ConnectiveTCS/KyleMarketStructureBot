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

@app.route('/api/status', methods=['GET'])
def api_status():
    """API: Get bot status"""
    global bot_thread
    status = 'running' if bot_thread and bot_thread.is_alive() else 'stopped'
    return jsonify({'status': status})

@app.route('/api/start', methods=['POST'])
def api_start():
    """API: Start the bot"""
    global bot_thread
    if not bot_thread or not bot_thread.is_alive():
        bot_thread = threading.Thread(target=start_bot)
        bot_thread.daemon = True
        bot_thread.start()
        return jsonify({'success': True, 'message': 'Bot started'})
    return jsonify({'success': False, 'message': 'Bot already running'})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    """API: Stop the bot"""
    global bot_thread
    if bot_thread and bot_thread.is_alive():
        stop_event.set()
        bot_thread = None
        return jsonify({'success': True, 'message': 'Bot stopping'})
    return jsonify({'success': False, 'message': 'Bot not running'})

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """API: Get or Update configuration"""
    if request.method == 'GET':
        try:
            config = load_config()
            return jsonify({'success': True, 'config': config})
        except Exception as e:
            return jsonify({'success': False, 'message': f"Error loading config: {str(e)}"}), 500
            
    elif request.method == 'POST':
        try:
            new_config_data = request.json
            if not isinstance(new_config_data, dict):
                 return jsonify({'success': False, 'message': 'Invalid JSON data format'}), 400
            
            if save_config(new_config_data):
                 return jsonify({'success': True, 'message': 'Configuration updated successfully'})
            else:
                 return jsonify({'success': False, 'message': 'Failed to save configuration'}), 500
        except Exception as e:
            return jsonify({'success': False, 'message': f"Error updating config: {str(e)}"}), 500

@app.route('/api/profiles', methods=['GET'])
def api_get_profiles():
    """API: Get list of available profiles"""
    profiles = get_available_profiles()
    return jsonify({'success': True, 'profiles': profiles})

@app.route('/api/profiles/<name>', methods=['POST', 'PUT', 'DELETE'])
def api_manage_profile(name):
    """API: Manage a specific profile (Save, Load, Delete)"""
    name = name.strip()
    if not name:
        return jsonify({'success': False, 'message': 'Profile name is required'}), 400

    if request.method == 'POST':
        success, message = save_profile(name)
        status_code = 200 if success else 500
        return jsonify({'success': success, 'message': message}), status_code

    elif request.method == 'PUT':
        success, message = load_profile(name)
        if success:
            api_stop()
            return jsonify({'success': True, 'message': message})
        else:
            status_code = 404 if "not found" in message else 500
            return jsonify({'success': False, 'message': message}), status_code

    elif request.method == 'DELETE':
        success, message = delete_profile(name)
        status_code = 200 if success else (404 if "not found" in message else 500)
        return jsonify({'success': success, 'message': message}), status_code

@app.route('/api/positions', methods=['GET'])
def api_get_positions():
    """API: Get open positions"""
    try:
        positions = get_positions()
        return jsonify({'success': True, 'positions': positions})
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error getting positions: {str(e)}"}), 500

@app.route('/api/history', methods=['GET'])
def api_get_history():
    """API: Get trade history with optional date filtering"""
    try:
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        limit_str = request.args.get('limit')
        
        from_date = None
        to_date = None
        limit = None

        if from_date_str:
            try:
                from_date = datetime.datetime.strptime(from_date_str, '%Y-%m-%d')
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid from_date format. Use YYYY-MM-DD.'}), 400
        
        if to_date_str:
            try:
                to_date = datetime.datetime.strptime(to_date_str, '%Y-%m-%d')
                to_date = to_date.replace(hour=23, minute=59, second=59)
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid to_date format. Use YYYY-MM-DD.'}), 400
        
        if limit_str:
             try:
                 limit = int(limit_str)
                 if limit <= 0:
                     limit = None
             except ValueError:
                 return jsonify({'success': False, 'message': 'Invalid limit format. Use a positive integer.'}), 400

        history = get_history(from_date=from_date, to_date=to_date, limit=limit)
        return jsonify({'success': True, 'history': history})
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error getting history: {str(e)}"}), 500

@app.route('/api/account', methods=['GET'])
def api_get_account_info():
    """API: Get account information"""
    try:
        account_info = get_account_info()
        if account_info:
            return jsonify({'success': True, 'account': account_info})
        else:
            return jsonify({'success': False, 'message': 'Could not retrieve account info'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error getting account info: {str(e)}"}), 500

@app.route('/api/market_structures', methods=['GET'])
def api_get_market_structures():
    """API: Get market structure data"""
    try:
        overall, structures = get_market_structures()
        return jsonify({'success': True, 'overall_direction': overall, 'structures': structures})
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error getting market structures: {str(e)}"}), 500

@app.route('/api/logs', methods=['GET'])
def api_get_logs():
    """API: Get logs with optional filtering"""
    try:
        level = request.args.get('level')
        component = request.args.get('component')
        n_str = request.args.get('n', '100')
        
        try:
            n = int(n_str)
        except ValueError:
             return jsonify({'success': False, 'message': 'Invalid number (n) format. Use an integer.'}), 400

        logs = get_logs(n=n, level=level, component=component)
        return jsonify({'success': True, 'logs': logs})
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error getting logs: {str(e)}"}), 500

@app.route('/api/strategies', methods=['GET'])
def api_get_strategies():
    """API: Get available strategies"""
    try:
        strategies = get_available_strategies()
        return jsonify({'success': True, 'strategies': strategies})
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error getting strategies: {str(e)}"}), 500

@app.route('/api/update/check', methods=['GET'])
def api_check_update():
    """API: Check for latest GitHub release version"""
    latest_version = get_latest_github_release()
    if latest_version:
        return jsonify({'success': True, 'latest_version': latest_version})
    else:
        return jsonify({'success': False, 'message': 'Could not check for updates'}), 503

@app.route('/api/update/trigger', methods=['POST'])
def api_trigger_update():
    """API: Trigger git pull and restart"""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(['git', 'pull'], cwd=root, capture_output=True, text=True, check=True)
        api_stop()
        return jsonify({'success': True, 'message': 'Update pulled. Restart required.', 'details': result.stdout})
    except subprocess.CalledProcessError as e:
         return jsonify({'success': False, 'message': 'Git pull failed.', 'details': e.stderr}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error triggering update: {str(e)}"}), 500

@app.route('/update_version')
def update_version():
    """Pull latest code from Git and restart (manual restart may still be needed)."""
    try:
        root = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(['git', 'pull'], cwd=root, capture_output=True, text=True)
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
            to_date = to_date.replace(hour=23, minute=59, second=59)
        else:
            to_date = datetime.datetime.now()
    except ValueError:
        from_date = datetime.datetime.now() - datetime.timedelta(days=30)
        to_date = datetime.datetime.now()
    
    return redirect(url_for('dashboard', 
                          from_date=from_date.strftime('%Y-%m-%d'),
                          to_date=to_date.strftime('%Y-%m-%d')) + '#history')

@app.route('/')
def dashboard():
    config = load_config()
    available_strategies = get_available_strategies()
    
    # --- Fetch real-time data for initial render ---
    current_price_real = None
    account_info_real = None
    positions_real = []
    history_real = []
    overall_direction_real, market_structures_real = None, []
    
    if mt5.initialize():
        symbol = config.get("symbol", "Step Index")
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            current_price_real = round((tick.bid + tick.ask) / 2, symbol_info.digits if (symbol_info := mt5.symbol_info(symbol)) else 5) # Use midpoint and round

        account_info_real = get_account_info() # Use existing function
        positions_real = get_positions() # Use existing function
        
        # Get history for default range (e.g., last 7 days) for initial view
        to_date_hist = datetime.datetime.now()
        from_date_hist = to_date_hist - datetime.timedelta(days=7)
        history_real = get_history(from_date=from_date_hist, to_date=to_date_hist, limit=50) # Limit initial history load
        
        overall_direction_real, market_structures_real = get_market_structures() # Use existing function
        
        # mt5.shutdown() # Consider if shutdown is needed here or managed elsewhere
    else:
        print("Failed to initialize MT5 for dashboard render")
        # Use defaults or indicate error state
        
    # --- Use fetched data (or defaults) in mock_data ---
    mock_data = {
        "symbol": config.get("symbol", "Step Index"),
        "timeframe": "H4", # This might still be a placeholder depending on your logic
        "status": 'running' if bot_thread and bot_thread.is_alive() else 'stopped', # Get real status
        "current_price": current_price_real if current_price_real is not None else "N/A", # Use fetched price
        "market_direction": overall_direction_real, # Use fetched overall direction
        "overall_direction": overall_direction_real, # Use fetched overall direction
        # Use the first structure's pivots as representative, or handle None
        "last_pivot_high": market_structures_real[0]['last_pivot_high'] if market_structures_real else None,
        "last_pivot_low": market_structures_real[0]['last_pivot_low'] if market_structures_real else None,
        "positions": positions_real, # Use fetched positions
        "history": history_real, # Use fetched history
        "logs": get_logs(n=100), # Keep log fetching as is, or adjust
        "account": account_info_real, # Use fetched account info
        "market_structures": market_structures_real, # Use fetched structures
        "profiles": get_available_profiles(),
        "available_strategies": available_strategies,
        "config": config
    }
    
    mock_data["stochastic"] = {
        "k_value": None,
        "d_value": None,
        "trend": None,
        "signal": None
    }
    
    active_strategy = config.get("active_strategy", "market_structure")
    if active_strategy == "stochastic":
        mock_data["stochastic"] = {
            "k_value": 25.5,
            "d_value": 20.3,
            "trend": "uptrend",
            "signal": "buy"
        }
    
    return render_template('dashboard.html', **mock_data)

@app.route('/logs')
def view_logs():
    log_level = request.args.get('level', None)
    log_component = request.args.get('component', None)
    logs = get_logs(n=100, level=log_level, component=log_component)
    log_components = get_available_components()
    
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
    
    for key, value in request.form.items():
        if value.lower() in ['true', 'false']:
            config[key] = value.lower() == 'true'
        elif value.replace('.', '', 1).isdigit():
            if '.' in value:
                config[key] = float(value)
            else:
                config[key] = int(value)
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
        global bot_thread
        stop_event.set()
        if bot_thread and bot_thread.is_alive():
            bot_thread.join(timeout=2)
        bot_thread = None
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

@app.route('/chart/<symbol>')
def chart_view(symbol):
    return render_template('chart_view.html', symbol=symbol)

@app.route('/api/candles')
def get_candles():
    symbol = request.args.get('symbol', '')
    timeframe = request.args.get('timeframe', '1h')
    
    try:
        candles = generate_demo_candles(timeframe)
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

@app.route('/api/indicator')
def get_indicator():
    symbol = request.args.get('symbol', '')
    indicator_type = request.args.get('type', '')
    period = int(request.args.get('period', 14))
    timeframe = request.args.get('timeframe', '1h')
    
    try:
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

def generate_demo_candles(timeframe):
    candles = []
    now = int(time.time())
    
    if timeframe.endswith('h'):
        interval = 3600 * int(timeframe[:-1])
    elif timeframe.endswith('d'):
        interval = 86400 * int(timeframe[:-1])
    elif timeframe.endswith('w'):
        interval = 604800 * int(timeframe[:-1])
    elif timeframe.endswith('m'):
        interval = 2592000 * int(timeframe[:-1])
    else:
        interval = 3600
    
    base_price = 100
    price = base_price
    
    for i in range(100):
        timestamp = now - (99 - i) * interval
        
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

def generate_demo_indicator(timeframe, indicator_type, period):
    values = []
    now = int(time.time())
    
    if timeframe.endswith('h'):
        interval = 3600 * int(timeframe[:-1])
    elif timeframe.endswith('d'):
        interval = 86400 * int(timeframe[:-1])
    elif timeframe.endswith('w'):
        interval = 604800 * int(timeframe[:-1])
    elif timeframe.endswith('m'):
        interval = 2592000 * int(timeframe[:-1])
    else:
        interval = 3600
    
    base_value = 100
    value = base_value
    
    for i in range(100):
        timestamp = now - (99 - i) * interval
        
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

def get_pivot_points(symbol, timeframe):
    now = int(time.time())
    
    if timeframe.endswith('h'):
        interval = 3600 * int(timeframe[:-1])
    elif timeframe.endswith('d'):
        interval = 86400 * int(timeframe[:-1])
    elif timeframe.endswith('w'):
        interval = 604800 * int(timeframe[:-1])
    elif timeframe.endswith('m'):
        interval = 2592000 * int(timeframe[:-1])
    else:
        interval = 3600
    
    base_price = 100
    
    pivot_highs = []
    for i in range(1, 6):
        timestamp = now - (90 - i * 15) * interval
        value = base_price + random.uniform(5, 10)
        pivot_highs.append({
            'time': timestamp,
            'value': round(value, 2)
        })
    
    pivot_lows = []
    for i in range(1, 6):
        timestamp = now - (82 - i * 15) * interval
        value = base_price - random.uniform(3, 8)
        pivot_lows.append({
            'time': timestamp,
            'value': round(value, 2)
        })
    
    return {
        'highs': pivot_highs,
        'lows': pivot_lows
    }

if __name__ == '__main__':
    is_service = not hasattr(sys, 'getwindowsversion')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    debug_mode = False if is_service else True
    app.run(host=host, port=port, debug=debug_mode)