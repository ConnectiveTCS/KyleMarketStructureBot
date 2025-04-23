import time
import json
import threading
import MetaTrader5 as mt5
import numpy as np
from datetime import datetime

# Load configuration
with open('config.json', 'r') as f:
    config = json.load(f)

SYMBOL = config['symbol']
# support multiple timeframes by precedence
TIMEFRAME_NAMES = config.get('timeframes', [config.get('timeframe')])
# map timeframe keys to MT5 constants, monthly uses TIMEFRAME_MN1
TF_CONST_MAP = {
    "TIMEFRAME_M1": mt5.TIMEFRAME_M1,
    "TIMEFRAME_M15": mt5.TIMEFRAME_M15,
    "TIMEFRAME_M30": mt5.TIMEFRAME_M30,
    "TIMEFRAME_H1": mt5.TIMEFRAME_H1,
    "TIMEFRAME_H4": mt5.TIMEFRAME_H4,
    "TIMEFRAME_D1": mt5.TIMEFRAME_D1,
    "TIMEFRAME_MN": mt5.TIMEFRAME_MN1
}
TIMEFRAMES = [TF_CONST_MAP[name] for name in TIMEFRAME_NAMES if name in TF_CONST_MAP]
# use lowest timeframe for order execution
TIMEFRAME = TIMEFRAMES[-1]

LOOKBACK = int(config['lookback'])
LOT_SIZE = float(config['lot_size'])
MAGIC = int(config['magic'])
MAX_POS = int(config['max_positions'])
UPDATE_INTERVAL = int(config['update_interval'])

# New configuration parameters
PIVOT_DEPTH = int(config.get('pivot_depth', 1))
BREAK_BUFFER_PIPS = float(config.get('break_buffer_pips', 0))
ATR_PERIOD = int(config.get('atr_period', 14))
ATR_MULT_SL = float(config.get('atr_multiplier_sl', 1.5))
ATR_MULT_TP = float(config.get('atr_multiplier_tp', 3.0))

# New configuration parameters for break-even and partial close
BREAK_EVEN_PIPS = float(config.get('break_even_pips', 0))
BREAK_EVEN_BUFFER = float(config.get('break_even_buffer_pips', 1))
PARTIAL_CLOSE_ENABLED = bool(config.get('partial_close_enabled', False))
PARTIAL_CLOSE_PCT = float(config.get('partial_close_pct', 50))
PARTIAL_CLOSE_PIPS = float(config.get('partial_close_pips', 0))

# New configuration parameters for enhanced strategy
RETEST_ENABLED = bool(config.get('retest_enabled', True))  # Enable retest entry method
DRAWDOWN_LIMIT_DAILY = float(config.get('drawdown_limit_daily', 5.0))  # Daily drawdown limit percentage
RISK_PER_TRADE = float(config.get('risk_per_trade', 1.0))  # Risk percentage per trade
SCALE_OUT_ENABLED = bool(config.get('scale_out_enabled', False))  # Enable scaling out
SCALE_OUT_TARGET = float(config.get('scale_out_target', 1.0))  # First target for scaling out (R:R ratio)

# Convert pips to price units
def pips_to_points(pips, symbol_info):
    digits = symbol_info.digits
    point = symbol_info.point
    
    pip_value = 0.0001
    if digits == 5 or digits == 3:
        pip_value = 10 * point
    elif digits == 4 or digits == 2:
        pip_value = point
    else:
        pip_value = point
    
    return pips * pip_value

# Calculate ATR
def calculate_atr(bars, period):
    trs = []
    for i in range(1, len(bars)):
        high, low = bars[i]['high'], bars[i]['low']
        prev = bars[i-1]['close']
        tr = max(high - low, abs(high - prev), abs(low - prev))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs)
    return sum(trs[-period:]) / period

# Identify pivot highs and lows with depth
def find_pivots(bars):
    highs, lows = [], []
    for i in range(PIVOT_DEPTH, len(bars) - PIVOT_DEPTH):
        window = bars[i - PIVOT_DEPTH:i + PIVOT_DEPTH + 1]
        highs_w = [b['high'] for b in window]
        lows_w = [b['low'] for b in window]
        if bars[i]['high'] == max(highs_w):
            highs.append((i, bars[i]['high']))
        if bars[i]['low'] == min(lows_w):
            lows.append((i, bars[i]['low']))
    return highs, lows

# Structure for tracking identified market structures
class MarketStructure:
    def __init__(self):
        self.last_trend = None  # 'uptrend' or 'downtrend'
        self.last_hh = None     # Last higher high price
        self.last_hl = None     # Last higher low price
        self.last_lh = None     # Last lower high price
        self.last_ll = None     # Last lower low price
        self.break_detected = False   # Structure break detected
        self.retest_level = None      # Price level for retest entry
        self.retest_direction = None  # Direction after break ('bull' or 'bear')
        self.waiting_for_retest = False  # Waiting for retest entry

# Dictionary to store market structure data for each timeframe
market_structures = {}

# Identify trend structure (higher highs/lows or lower highs/lows)
def identify_trend_structure(bars, timeframe):
    # Get or create market structure tracker for this timeframe
    if timeframe not in market_structures:
        market_structures[timeframe] = MarketStructure()
    
    ms = market_structures[timeframe]
    
    # We need at least 4 pivot points to identify a trend structure
    highs, lows = find_pivots(bars)
    
    if len(highs) < 2 or len(lows) < 2:
        return ms
    
    # Get the last two pivot highs and lows
    last_two_highs = sorted(highs[-2:])
    last_two_lows = sorted(lows[-2:])
    
    # Check for uptrend (higher highs and higher lows)
    if highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]:
        ms.last_trend = 'uptrend'
        ms.last_hh = highs[-1][1]
        ms.last_hl = lows[-1][1]
    
    # Check for downtrend (lower highs and lower lows)
    elif highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]:
        ms.last_trend = 'downtrend'
        ms.last_lh = highs[-1][1]
        ms.last_ll = lows[-1][1]
        
    return ms

# Enhanced check for market structure breaks with retest logic
def check_structure_break(bars, symbol_info, timeframe):
    ms = identify_trend_structure(bars, timeframe)
    
    if len(bars) == 0:
        return None
    
    last_close = bars[-1]['close']
    buffer = pips_to_points(BREAK_BUFFER_PIPS, symbol_info)
    
    # If we're waiting for a retest, check if it happened
    if ms.waiting_for_retest and ms.retest_level:
        if ms.retest_direction == 'bull':
            # For long entries, check if price came back near the retest level (former resistance now support)
            if abs(last_close - ms.retest_level) < buffer:
                # Check for bullish price action (close > open)
                if bars[-1]['close'] > bars[-1]['open']:
                    ms.waiting_for_retest = False
                    return 'bull_retest'
        elif ms.retest_direction == 'bear':
            # For short entries, check if price came back near the retest level (former support now resistance)
            if abs(last_close - ms.retest_level) < buffer:
                # Check for bearish price action (close < open)
                if bars[-1]['close'] < bars[-1]['open']:
                    ms.waiting_for_retest = False
                    return 'bear_retest'
    
    # Check for structure breaks
    if ms.last_trend == 'downtrend' and ms.last_lh and last_close > ms.last_lh + buffer:
        # Bullish break of structure (price broke above the last lower high)
        if RETEST_ENABLED:
            ms.retest_level = ms.last_lh
            ms.retest_direction = 'bull'
            ms.waiting_for_retest = True
            return 'bull_break'
        else:
            return 'bull'
            
    elif ms.last_trend == 'uptrend' and ms.last_hl and last_close < ms.last_hl - buffer:
        # Bearish break of structure (price broke below the last higher low)
        if RETEST_ENABLED:
            ms.retest_level = ms.last_hl
            ms.retest_direction = 'bear'
            ms.waiting_for_retest = True
            return 'bear_break'
        else:
            return 'bear'
    
    return None

# Check for break of market structure with buffer
def check_break(bars, highs, lows, symbol_info):
    last_close = bars[-1]['close']
    buffer = pips_to_points(BREAK_BUFFER_PIPS, symbol_info)
    if highs:
        _, last_high = highs[-1]
        if last_close > last_high + buffer:
            return 'bull'
    if lows:
        _, last_low = lows[-1]
        if last_close < last_low - buffer:
            return 'bear'
    return None

# Check if position should be moved to break-even
def check_break_even(position, symbol_info):
    if BREAK_EVEN_PIPS <= 0:
        return False
    
    # Calculate pip value for this symbol
    pip_value = pips_to_points(1.0, symbol_info)
    
    # Calculate break-even threshold
    break_even_threshold = BREAK_EVEN_PIPS * pip_value
    buffer = BREAK_EVEN_BUFFER * pip_value
    
    # Get current price
    tick = mt5.symbol_info_tick(position.symbol)
    current_bid, current_ask = tick.bid, tick.ask
    
    # Check if already at break-even (stop loss at or better than entry)
    if position.type == mt5.POSITION_TYPE_BUY and position.sl >= position.price_open:
        return False
    if position.type == mt5.POSITION_TYPE_SELL and position.sl <= position.price_open:
        return False
    
    # Check if position is in enough profit to move to break-even
    if position.type == mt5.POSITION_TYPE_BUY:
        profit_pips = current_bid - position.price_open
        if profit_pips >= break_even_threshold:
            new_sl = position.price_open + buffer
            return new_sl
    else:  # SELL position
        profit_pips = position.price_open - current_ask
        if profit_pips >= break_even_threshold:
            new_sl = position.price_open - buffer
            return new_sl
    
    return False

# Check if position should be partially closed
def check_partial_close(position, symbol_info):
    if not PARTIAL_CLOSE_ENABLED or PARTIAL_CLOSE_PIPS <= 0 or PARTIAL_CLOSE_PCT <= 0:
        return False
    
    # If position has already been partially closed (check volume)
    original_volume = LOT_SIZE  # Assuming all positions start with the same lot size
    if position.volume < original_volume * 0.99:  # Allow for small rounding differences
        return False
    
    # Calculate pip value for this symbol
    pip_value = pips_to_points(1.0, symbol_info)
    
    # Calculate partial close threshold
    partial_close_threshold = PARTIAL_CLOSE_PIPS * pip_value
    
    # Get current price
    tick = mt5.symbol_info_tick(position.symbol)
    current_bid, current_ask = tick.bid, tick.ask
    
    # Check if position is in enough profit for partial close
    if position.type == mt5.POSITION_TYPE_BUY:
        profit_pips = current_bid - position.price_open
        if profit_pips >= partial_close_threshold:
            return True
    else:  # SELL position
        profit_pips = position.price_open - current_ask
        if profit_pips >= partial_close_threshold:
            return True
    
    return False

# Move position to break-even
def move_to_break_even(position, new_sl):
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": position.symbol,
        "position": position.ticket,
        "sl": new_sl,
        "tp": position.tp,
        "magic": MAGIC
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Error moving position {position.ticket} to break-even: {result.retcode}")
    else:
        print(f"Position {position.ticket} moved to break-even: SL={new_sl}")
    return result

# Partially close a position
def partial_close(position):
    # Calculate volume to close
    close_volume = position.volume * (PARTIAL_CLOSE_PCT / 100.0)
    
    # Ensure we don't close more than the position size
    close_volume = min(close_volume, position.volume)
    
    # MetaTrader minimum volume is usually 0.01
    if close_volume < 0.01:
        close_volume = 0.01
    
    # Round to 2 decimal places
    close_volume = round(close_volume, 2)
    
    # Create close request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": close_volume,
        "type": mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "position": position.ticket,
        "price": mt5.symbol_info_tick(position.symbol).bid if position.type == mt5.POSITION_TYPE_BUY else mt5.symbol_info_tick(position.symbol).ask,
        "deviation": 20,
        "magic": MAGIC,
        "comment": "partial close",
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Error partially closing position {position.ticket}: {result.retcode}")
    else:
        print(f"Position {position.ticket} partially closed: {close_volume} lots")
    return result

# Enhanced entry logic with proper stop-loss based on structure
def enter_trade(direction, symbol_info, bars, highs, lows):
    # Check for drawdown limit before entering trade
    if check_drawdown_limit():
        print(f"Daily drawdown limit of {DRAWDOWN_LIMIT_DAILY}% reached. No new trades.")
        return
    
    # Get current tick
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        print("Failed to get current price tick")
        return
    
    # Determine price, SL, and TP
    atr = calculate_atr(bars, ATR_PERIOD)
    
    if 'bull' in direction:
        # For long entries
        entry_price = tick.ask
        
        # Set stop loss below the recent HL (higher low) or last pivot low
        if lows and len(lows) > 0:
            stop_loss = lows[-1][1] - pips_to_points(BREAK_BUFFER_PIPS, symbol_info)
        else:
            stop_loss = entry_price - atr * ATR_MULT_SL
            
        # Set take profit target based on risk-reward ratio
        sl_distance = entry_price - stop_loss
        take_profit = entry_price + (sl_distance * ATR_MULT_TP)
        
        order_type = mt5.ORDER_TYPE_BUY
        
    else:
        # For short entries
        entry_price = tick.bid
        
        # Set stop loss above the recent LH (lower high) or last pivot high
        if highs and len(highs) > 0:
            stop_loss = highs[-1][1] + pips_to_points(BREAK_BUFFER_PIPS, symbol_info)
        else:
            stop_loss = entry_price + atr * ATR_MULT_SL
            
        # Set take profit target based on risk-reward ratio
        sl_distance = stop_loss - entry_price
        take_profit = entry_price - (sl_distance * ATR_MULT_TP)
        
        order_type = mt5.ORDER_TYPE_SELL
    
    # Calculate position size based on risk percentage
    volume = calculate_position_size(direction, entry_price, stop_loss, symbol_info)
    
    # Place the trade
    request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'symbol': SYMBOL,
        'volume': volume,
        'type': order_type,
        'price': entry_price,
        'sl': stop_loss,
        'tp': take_profit,
        'magic': MAGIC,
        'comment': f'market structure {direction}',
        'type_filling': mt5.ORDER_FILLING_FOK,
    }
    
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order send failed: {result.retcode}, {result.comment}")
    else:
        print(f"Order placed successfully: {direction} {volume} lots at {entry_price}, SL: {stop_loss}, TP: {take_profit}")
        
        # If scaling out is enabled, set up second position with different TP
        if SCALE_OUT_ENABLED and volume >= 0.02:
            # Calculate position size for the scale-out
            scale_volume = round(volume * 0.5, 2)  # 50% of original position
            if scale_volume >= 0.01:  # Minimum 0.01 lot
                # Calculate first target using scale out setting
                sl_distance = abs(entry_price - stop_loss)
                scale_tp = entry_price + (sl_distance * SCALE_OUT_TARGET) if 'bull' in direction else entry_price - (sl_distance * SCALE_OUT_TARGET)
                
                # Place the scaled position
                scale_request = request.copy()
                scale_request['volume'] = scale_volume
                scale_request['tp'] = scale_tp
                scale_request['comment'] = f'market structure {direction} scale-out'
                
                scale_result = mt5.order_send(scale_request)
                if scale_result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"Scale-out position placed: {scale_volume} lots, TP: {scale_tp}")
    
    return result

# Log trade to journal
def log_trade(direction, entry_price, stop_loss, take_profit, volume, result):
    try:
        with open('trade_journal.csv', 'a') as f:
            # Write header if file is empty
            if f.tell() == 0:
                f.write("timestamp,symbol,direction,entry,stop_loss,take_profit,volume,ticket\n")
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ticket = result.order if hasattr(result, 'order') else 0
            f.write(f"{timestamp},{SYMBOL},{direction},{entry_price},{stop_loss},{take_profit},{volume},{ticket}\n")
    except Exception as e:
        print(f"Error logging trade: {e}")

# Check drawdown limit
def check_drawdown_limit(account_balance, current_drawdown, max_drawdown_percent=5):
    """
    Check if a trade would exceed the maximum allowed drawdown limit.
    
    Args:
        account_balance (float): Current account balance
        current_drawdown (float): Current drawdown amount
        max_drawdown_percent (float): Maximum allowed drawdown as percentage of account balance
        
    Returns:
        bool: True if drawdown is within acceptable limits, False otherwise
    """
    max_allowed_drawdown = account_balance * (max_drawdown_percent / 100)
    
    # Return True if current drawdown is less than maximum allowed drawdown
    return current_drawdown < max_allowed_drawdown

# Calculate position size
def calculate_position_size(account_balance, risk_per_trade, entry_price, stop_loss):
    """
    Calculate position size based on risk management parameters.
    
    Args:
        account_balance (float): Current account balance
        risk_per_trade (float): Percentage of account balance to risk per trade
        entry_price (float): Planned entry price
        stop_loss (float): Planned stop loss price
        
    Returns:
        float: Position size in base currency
    """
    if entry_price == stop_loss:
        return 0  # Avoid division by zero
    
    # Calculate risk amount in account currency
    risk_amount = account_balance * (risk_per_trade / 100)
    
    # Calculate position size based on risk and stop distance
    stop_distance = abs(entry_price - stop_loss)
    position_size = risk_amount / stop_distance
    
    return position_size

# Main bot loop
def run(stop_event):
    if not mt5.initialize():
        print("MT5 initialization failed")
        return
    if not mt5.symbol_select(SYMBOL, True):
        print(f"Failed to select symbol {SYMBOL}")
        mt5.shutdown()
        return

    symbol_info = mt5.symbol_info(SYMBOL)
    triggered_timeframes = {}
    last_day = datetime.now().day

    while not stop_event.is_set():
        current_day = datetime.now().day
        if current_day != last_day:
            triggered_timeframes = {}
            last_day = current_day

        if check_drawdown_limit():
            print(f"Daily drawdown limit reached. Waiting for next day.")
            time.sleep(UPDATE_INTERVAL)
            continue

        positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC) or []
        
        for position in positions:
            new_sl = check_break_even(position, symbol_info)
            if new_sl:
                move_to_break_even(position, new_sl)
            
            if check_partial_close(position, symbol_info):
                partial_close(position)
        
        dir_map = {}
        pivot_map = {}
        for name, tf in zip(TIMEFRAME_NAMES, TIMEFRAMES):
            bars = mt5.copy_rates_from_pos(SYMBOL, tf, 0, LOOKBACK)
            if bars is None:
                bars = []
                
            if len(bars) < LOOKBACK:
                continue
                
            highs, lows = find_pivots(bars)
            # Update to pass the timeframe name for market structure tracking
            direction = check_structure_break(bars, symbol_info, name)
            
            dir_map[name] = direction
            pivot_map[name] = (highs, lows, bars)
            
            if name in triggered_timeframes:
                continue
                
        current_positions = len(positions)
        if current_positions < MAX_POS:
            for name in TIMEFRAME_NAMES:
                if name not in dir_map or not dir_map[name]:
                    continue
                    
                if name in triggered_timeframes:
                    continue
                    
                direction = dir_map[name]
                
                if direction in ['bull', 'bear', 'bull_retest', 'bear_retest']:
                    highs, lows, bars = pivot_map[name]
                    result = enter_trade(direction, symbol_info, bars, highs, lows)
                    
                    if result and hasattr(result, 'order') and result.order > 0:
                        triggered_timeframes[name] = True
                        
                        tick = mt5.symbol_info_tick(SYMBOL)
                        entry_price = tick.ask if 'bull' in direction else tick.bid
                        stop_loss = lows[-1][1] if 'bull' in direction else highs[-1][1]
                        sl_distance = abs(entry_price - stop_loss)
                        take_profit = entry_price + sl_distance * ATR_MULT_TP if 'bull' in direction else entry_price - sl_distance * ATR_MULT_TP
                        volume = calculate_position_size(direction, entry_price, stop_loss, symbol_info)
                        
                        log_trade(direction, entry_price, stop_loss, take_profit, volume, result)
                        break
        
        time.sleep(UPDATE_INTERVAL)

    mt5.shutdown()

if __name__ == '__main__':
    stop_flag = threading.Event()
    try:
        run(stop_flag)
    except KeyboardInterrupt:
        stop_flag.set()