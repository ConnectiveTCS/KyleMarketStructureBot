import time
import json
import threading
import MetaTrader5 as mt5
from logs import get_logger
import ast

# Create a logger for this module
logger = get_logger('bot')

# Load configuration
with open('config.json', 'r') as f:
    config = json.load(f)

SYMBOL = config['symbol']
# Support multiple timeframes by precedence
if 'timeframes' in config:
    if isinstance(config['timeframes'], list):
        TIMEFRAME_NAMES = config['timeframes']
    elif isinstance(config['timeframes'], str):
        # Try to parse string representation of list
        try:
            # Handle both formats: "['TIMEFRAME_H4', ...]" and '["TIMEFRAME_H4", ...]'
            TIMEFRAME_NAMES = ast.literal_eval(config['timeframes'])
        except (SyntaxError, ValueError):
            logger.warning(f"Invalid timeframes format: {config['timeframes']}. Using default.")
            TIMEFRAME_NAMES = ["TIMEFRAME_M15"]
    else:
        TIMEFRAME_NAMES = ["TIMEFRAME_M15"]  # Default timeframe
elif 'timeframe' in config:
    TIMEFRAME_NAMES = [config['timeframe']]
else:
    TIMEFRAME_NAMES = ["TIMEFRAME_M15"]  # Default timeframe

# map timeframe keys to MT5 constants, monthly uses TIMEFRAME_MN1
TF_CONST_MAP = {
    "TIMEFRAME_M1": mt5.TIMEFRAME_M1,
    "TIMEFRAME_M5": mt5.TIMEFRAME_M5,
    "TIMEFRAME_M15": mt5.TIMEFRAME_M15,
    "TIMEFRAME_M30": mt5.TIMEFRAME_M30,
    "TIMEFRAME_H1": mt5.TIMEFRAME_H1,
    "TIMEFRAME_H4": mt5.TIMEFRAME_H4,
    "TIMEFRAME_D1": mt5.TIMEFRAME_D1,
    "TIMEFRAME_W1": mt5.TIMEFRAME_W1,
    "TIMEFRAME_MN1": mt5.TIMEFRAME_MN1,
}

logger.info(f"Configured timeframes: {TIMEFRAME_NAMES}")
TIMEFRAMES = [TF_CONST_MAP[name] for name in TIMEFRAME_NAMES if name in TF_CONST_MAP]

# Check if TIMEFRAMES is empty and handle the error
if not TIMEFRAMES:
    logger.warning(f"No valid timeframes found in configuration. Using TIMEFRAME_M15 as default.")
    TIMEFRAMES = [mt5.TIMEFRAME_M15]  # Use M15 as default
    
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
USE_DYNAMIC_SL = bool(config.get('use_dynamic_sl', False)) # Load the new parameter

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

# Check for break of market structure with buffer
def check_break(bars, highs, lows, symbol_info):
    # avoid IndexError when no bars available
    if bars is None or len(bars) == 0:
        logger.debug("check_break: received empty bars list")
        return None
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
        logger.error(f"Error moving position {position.ticket} to break-even: {result.retcode}")
    else:
        logger.info(f"Position {position.ticket} moved to break-even: SL={new_sl}")
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
        logger.error(f"Error partially closing position {position.ticket}: {result.retcode}")
    else:
        logger.info(f"Position {position.ticket} partially closed: {close_volume} lots")
    return result

# Entry logic with ATR-based SL/TP or Dynamic SL based on swing points
def enter_trade(direction, symbol_info, last_high, last_low):
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, LOOKBACK)
    atr = calculate_atr(rates, ATR_PERIOD)
    tick = mt5.symbol_info_tick(SYMBOL)
    buffer_points = pips_to_points(BREAK_BUFFER_PIPS, symbol_info)

    if direction == 'bull':
        price = tick.ask
        tp = price + atr * ATR_MULT_TP # TP remains ATR based for now
        order_type = mt5.ORDER_TYPE_BUY
        if USE_DYNAMIC_SL and last_low is not None:
            sl = last_low - buffer_points
            logger.info(f"Using dynamic SL for BUY based on last low: {last_low}")
        else:
            sl = price - atr * ATR_MULT_SL
            logger.info(f"Using ATR-based SL for BUY")
    else: # direction == 'bear'
        price = tick.bid
        tp = price - atr * ATR_MULT_TP # TP remains ATR based for now
        order_type = mt5.ORDER_TYPE_SELL
        if USE_DYNAMIC_SL and last_high is not None:
            sl = last_high + buffer_points
            logger.info(f"Using dynamic SL for SELL based on last high: {last_high}")
        else:
            sl = price + atr * ATR_MULT_SL
            logger.info(f"Using ATR-based SL for SELL")

    # Ensure SL is valid (e.g., SL for buy is below price, SL for sell is above price)
    if order_type == mt5.ORDER_TYPE_BUY and sl >= price:
        logger.warning(f"Calculated dynamic SL ({sl}) is above entry price ({price}). Reverting to ATR SL.")
        sl = price - atr * ATR_MULT_SL
    elif order_type == mt5.ORDER_TYPE_SELL and sl <= price:
        logger.warning(f"Calculated dynamic SL ({sl}) is below entry price ({price}). Reverting to ATR SL.")
        sl = price + atr * ATR_MULT_SL
        
    # Ensure SL is not zero or negative if required by broker
    if sl <= 0:
        logger.warning(f"Calculated SL ({sl}) is zero or negative. Reverting to ATR SL.")
        if order_type == mt5.ORDER_TYPE_BUY:
            sl = price - atr * ATR_MULT_SL
        else:
            sl = price + atr * ATR_MULT_SL
            
    request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'symbol': SYMBOL,
        'volume': LOT_SIZE,
        'type': order_type,
        'price': price,
        'sl': sl,
        'tp': tp,
        'magic': MAGIC,
        'comment': 'market structure bot',
        'type_filling': mt5.ORDER_FILLING_FOK,
    }
    result = mt5.order_send(request)
    logger.info(f"OrderSend result: {result}")

# Main bot loop
def run(stop_event):
    logger.info("Bot starting...")
    if not mt5.initialize():
        logger.error("MT5 initialization failed")
        return
    if not mt5.symbol_select(SYMBOL, True):
        logger.error(f"Failed to select symbol {SYMBOL}")
        mt5.shutdown()
        return

    symbol_info = mt5.symbol_info(SYMBOL)
    while not stop_event.is_set():
        # Check existing positions for break-even and partial close
        positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC) or []
        
        for position in positions:
            # Check for break-even opportunity
            new_sl = check_break_even(position, symbol_info)
            if new_sl:
                move_to_break_even(position, new_sl)
            
            # Check for partial close opportunity
            if check_partial_close(position, symbol_info):
                partial_close(position)
        
        # multi‐TF structure checks
        dir_map = {}
        pivot_map = {}
        for name, tf in zip(TIMEFRAME_NAMES, TIMEFRAMES):
            bars = mt5.copy_rates_from_pos(SYMBOL, tf, 0, LOOKBACK)
            if bars is None:
                bars = []
            highs, lows = find_pivots(bars)
            dir_map[name] = check_break(bars, highs, lows, symbol_info)
            pivot_map[name] = (highs, lows)
        # pick first TF with a break
        trigger = next((n for n in TIMEFRAME_NAMES if dir_map.get(n)), None)
        direction = dir_map.get(trigger)

        positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC) or []
        if trigger and direction and len(positions) < MAX_POS:
            # Get pivots from the *triggering* timeframe
            highs, lows = pivot_map[trigger]
            last_high = highs[-1][1] if highs else None
            last_low  = lows[-1][1]  if lows  else None
            # Pass last high/low to enter_trade for dynamic SL calculation
            enter_trade(direction, symbol_info, last_high, last_low)

        time.sleep(UPDATE_INTERVAL)

    mt5.shutdown()
    logger.info("Bot stopping...")

# Allow running from script
if __name__ == '__main__':
    stop_flag = threading.Event()
    try:
        run(stop_flag)
    except KeyboardInterrupt:
        stop_flag.set()