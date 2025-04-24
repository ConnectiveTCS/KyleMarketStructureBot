import threading
import json
import datetime  # Import the standard datetime module
import os  # Add this import
from flask import Flask, render_template, request, redirect, url_for, jsonify  # Add jsonify
import bot as trading_bot
import MetaTrader5 as mt5
# Import the logs module
from logs import get_logs, get_available_components

app = Flask(__name__)
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
    with open('config.json', 'r') as f:
        cfg = json.load(f)
    symbol = cfg['symbol']
    magic = cfg['magic']
    all_pos = mt5.positions_get() or []
    # filter by symbol & magic
    open_pos = [p for p in all_pos if p.symbol == symbol and p.magic == magic]
    return [format_position(p) for p in open_pos]

# Get trade history
def get_history(limit=10):
    if not mt5.initialize():
        return []
    with open('config.json', 'r') as f:
        cfg = json.load(f)
    magic = cfg['magic']
    # last 2 weeks
    to_date = datetime.datetime.now()
    from_date = to_date - datetime.timedelta(days=14)
    deals = mt5.history_deals_get(from_date, to_date) or []
    # filter by magic
    my_deals = [d for d in deals if getattr(d, 'magic', None) == magic]
    trades = process_history(my_deals)
    return trades[:limit]

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
    with open('config.json', 'r') as f:
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
        current_price = (tick.bid + tick.ask) / 2
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

@app.route('/')
def dashboard():
    with open('config.json', 'r') as f:
        config = json.load(f)
    status = 'running' if bot_thread and bot_thread.is_alive() else 'stopped'
    
    # Get monitoring data
    positions = get_positions()
    history = get_history()
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
                          profiles=profiles)  # Add profiles here

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
        # Handle boolean values from form
        if val.lower() == 'true':
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
    with open('config.json', 'r') as f:
        current_config = json.load(f)
        
    # Merge configs (this keeps arrays like timeframes)
    for key, val in current_config.items():
        if key not in new_conf:
            new_conf[key] = val
            
    with open('config.json', 'w') as f:
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
    return jsonify({'success': success, 'message': message})

@app.route('/delete_profile')
def delete_profile_route():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Profile name is required'})
    
    success, message = delete_profile(name)
    return jsonify({'success': success, 'message': message})

if __name__ == '__main__':
    app.run(debug=True)