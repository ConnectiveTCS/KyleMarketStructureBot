import threading
import json
import datetime  # Import the standard datetime module
import os  # Add this import
import sys  # Add this import for the system module
from flask import Flask, render_template, request, redirect, url_for, jsonify  # Add jsonify
import bot as trading_bot
import MetaTrader5 as mt5
# Import the logs module
from logs import get_logs, get_available_components

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
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    status = 'running' if bot_thread and bot_thread.is_alive() else 'stopped'
    
    # Get date filter parameters
    from_date_str = request.args.get('from_date')
    to_date_str = request.args.get('to_date')
    
    try:
        if from_date_str:
            from_date = datetime.datetime.strptime(from_date_str, '%Y-%m-%d')
        else:
            # Default to the last 30 days
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
    
    # Get monitoring data
    positions = get_positions()
    history = get_history(from_date=from_date, to_date=to_date)
    account = get_account_info()
    
    # Get market structures data
    overall, market_structures = get_market_structures()
    
    # Get individual structure details for the original template variables
    # Use the first timeframe structure or set defaults
    primary_structure = market_structures[0] if market_structures else {}
    symbol = config['symbol']
    timeframe = primary_structure.get('timeframe', 'N/A')
    market_direction = primary_structure.get('market_direction')
    current_price = primary_structure.get('current_price')
    last_pivot_high = primary_structure.get('last_pivot_high')
    pivot_high_time = primary_structure.get('pivot_high_time')
    last_pivot_low = primary_structure.get('last_pivot_low')
    pivot_low_time = primary_structure.get('pivot_low_time')
    
    # Get logs for the dashboard
    log_level = request.args.get('level', None)
    log_component = request.args.get('component', None)
    logs = get_logs(n=100, level=log_level, component=log_component)
    log_components = get_available_components()
    
    # Get available profiles
    profiles = get_available_profiles()
    
    return render_template('dashboard.html', 
                          config=config, 
                          status=status,
                          positions=positions,
                          history=history,
                          account=account,
                          overall_direction=overall,
                          market_structures=market_structures,
                          # Add individual structure details for backward compatibility
                          symbol=symbol,
                          timeframe=timeframe,
                          market_direction=market_direction,
                          current_price=current_price,
                          last_pivot_high=last_pivot_high,
                          pivot_high_time=pivot_high_time, 
                          last_pivot_low=last_pivot_low,
                          pivot_low_time=pivot_low_time,
                          logs=logs,
                          log_level=log_level,
                          log_component=log_component,
                          log_components=log_components,
                          profiles=profiles,
                          # Add date filter parameters
                          from_date=from_date.strftime('%Y-%m-%d'),
                          to_date=to_date.strftime('%Y-%m-%d'))

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
    new_conf = {}
    for key, val in request.form.items():
        # Special handling for timeframes field
        if key == 'timeframes':
            try:
                # If it contains square brackets, try to parse it as JSON
                if '[' in val and ']' in val:
                    # Clean up the input to ensure it's valid JSON
                    # Remove single quotes, ensure double quotes for array items
                    cleaned_val = val.replace("'", '"')
                    new_conf[key] = json.loads(cleaned_val)
                else:
                    # If it's a single timeframe, make it a list
                    new_conf[key] = [val]
            except json.JSONDecodeError:
                # If JSON parsing fails, keep as string but log warning
                new_conf[key] = val
                print(f"Warning: Could not parse timeframes value: {val}")
        # Handle boolean values from form
        elif val.lower() == 'true':
            new_conf[key] = True
        elif val.lower() == 'false':
            new_conf[key] = False
        # try to cast to int or float
        elif val.isdigit():
            new_conf[key] = int(val)
        else:
            try:
                new_conf[key] = float(val)
            except:
                new_conf[key] = val
                
    # Load current config to preserve array values that might not be in form
    with open(CONFIG_FILE, 'r') as f:
        current_config = json.load(f)
        
    # Merge configs (this keeps arrays like timeframes)
    for key, val in current_config.items():
        if key not in new_conf:
            new_conf[key] = val
            
    with open(CONFIG_FILE, 'w') as f:
        json.dump(new_conf, f, indent=4)
    return redirect(url_for('dashboard'))

# Profile management routes
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