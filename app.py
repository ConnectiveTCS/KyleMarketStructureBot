import threading
import json
import datetime
import csv
import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
import bot as trading_bot
import MetaTrader5 as mt5

app = Flask(__name__)
bot_thread = None
stop_event = threading.Event()

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

# Get trade journal data
def get_trade_journal(limit=20):
    journal_data = []
    try:
        if os.path.exists('trade_journal.csv'):
            with open('trade_journal.csv', 'r') as f:
                reader = csv.DictReader(f)
                journal_data = list(reader)[-limit:]  # Get last 'limit' entries
    except Exception as e:
        print(f"Error reading trade journal: {e}")
    return journal_data

# Calculate performance metrics
def get_performance_metrics():
    metrics = {
        'win_rate': 0,
        'avg_win': 0,
        'avg_loss': 0,
        'profit_factor': 0,
        'total_trades': 0,
        'winning_trades': 0,
        'losing_trades': 0
    }
    
    # Get closed trades from history
    history = get_history(100)  # Last 100 trades
    if not history:
        return metrics
    
    # Calculate metrics
    metrics['total_trades'] = len(history)
    winning_trades = [t for t in history if t['profit'] > 0]
    losing_trades = [t for t in history if t['profit'] < 0]
    
    metrics['winning_trades'] = len(winning_trades)
    metrics['losing_trades'] = len(losing_trades)
    
    if metrics['total_trades'] > 0:
        metrics['win_rate'] = (metrics['winning_trades'] / metrics['total_trades']) * 100
    
    if metrics['winning_trades'] > 0:
        metrics['avg_win'] = sum(t['profit'] for t in winning_trades) / metrics['winning_trades']
    
    if metrics['losing_trades'] > 0:
        metrics['avg_loss'] = abs(sum(t['profit'] for t in losing_trades) / metrics['losing_trades'])
    
    total_profit = sum(t['profit'] for t in winning_trades)
    total_loss = abs(sum(t['profit'] for t in losing_trades))
    
    if total_loss > 0:
        metrics['profit_factor'] = total_profit / total_loss
    
    return metrics

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
        
        # Add trend analysis with safe access to market_structures
        trend_type = 'neutral'
        market_structure = None
        
        # Check if market_structures exists in the module and if this timeframe has data
        if hasattr(trading_bot, 'market_structures') and name in trading_bot.market_structures:
            market_structure = trading_bot.market_structures[name]
            trend_type = market_structure.last_trend if market_structure and market_structure.last_trend else 'neutral'
        
        # Add structure information (safely)
        structures[-1]['trend_type'] = trend_type
        
        # Add additional fields only if we have market structure data
        if market_structure:
            structures[-1]['higher_high'] = market_structure.last_hh
            structures[-1]['higher_low'] = market_structure.last_hl
            structures[-1]['lower_high'] = market_structure.last_lh
            structures[-1]['lower_low'] = market_structure.last_ll
            structures[-1]['waiting_for_retest'] = market_structure.waiting_for_retest
            structures[-1]['retest_level'] = market_structure.retest_level
        else:
            # Add default values when no market structure data is available
            structures[-1]['higher_high'] = None
            structures[-1]['higher_low'] = None
            structures[-1]['lower_high'] = None
            structures[-1]['lower_low'] = None
            structures[-1]['waiting_for_retest'] = False
            structures[-1]['retest_level'] = None
    
    overall = next((s['market_direction'] for s in structures if s['market_direction']), None)
    return overall, structures

@app.route('/')
def index():
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
    
    # Get enhanced data for dashboard
    performance = get_performance_metrics()
    journal = get_trade_journal(10)
    
    return render_template('dashboard.html', 
                          config=config, 
                          status=status,
                          positions=positions,
                          history=history,
                          account=account,
                          overall_direction=overall,
                          market_structures=market_structures,
                          performance=performance,
                          journal=journal,
                          # Add individual structure details for backward compatibility
                          symbol=symbol,
                          timeframe=timeframe,
                          market_direction=market_direction,
                          current_price=current_price,
                          last_pivot_high=last_pivot_high,
                          pivot_high_time=pivot_high_time, 
                          last_pivot_low=last_pivot_low,
                          pivot_low_time=pivot_low_time)

@app.route('/start')
def start():
    global bot_thread
    if not bot_thread or not bot_thread.is_alive():
        bot_thread = threading.Thread(target=start_bot)
        bot_thread.daemon = True
        bot_thread.start()
    return redirect(url_for('index'))

@app.route('/stop')
def stop():
    stop_event.set()
    return redirect(url_for('index'))

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
    return redirect(url_for('index'))

# New API endpoint for AJAX updates
@app.route('/api/data')
def api_data():
    overall, market_structures = get_market_structures()
    positions = get_positions()
    account = get_account_info()
    
    return jsonify({
        'overall_direction': overall,
        'market_structures': market_structures,
        'positions': positions,
        'account': account
    })

if __name__ == '__main__':
    app.run(debug=True)