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
    TIMEFRAME_NAMES = ["TIMEFRAME_M1"]  # Default timeframe

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

# Minimum required timeframes for confirmation
MIN_TF_CONFIRMATION = int(config.get('min_tf_confirmation', 2))

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

# Custom normalize_price function since MT5 doesn't provide one
def normalize_price(price, digits):
    """
    Normalize price to the specified number of digits (decimal places).
    Replacement for the missing mt5.normalize_price function.
    
    Args:
        price: The price value to normalize
        digits: Number of decimal places
        
    Returns:
        float: Normalized price value
    """
    if price is None:
        return None
    
    multiplier = 10 ** digits
    return round(price * multiplier) / multiplier

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

# Enhanced check for partial close - only trigger after break-even is hit
def check_partial_close(position, symbol_info):
    if not PARTIAL_CLOSE_ENABLED or PARTIAL_CLOSE_PIPS <= 0:
        return False
    
    # Only attempt partial close if break-even has been triggered
    if position.type == mt5.POSITION_TYPE_BUY and position.sl < position.price_open:
        return False  # Break-even not yet triggered for buy
    
    if position.type == mt5.POSITION_TYPE_SELL and position.sl > position.price_open:
        return False  # Break-even not yet triggered for sell
    
    # Calculate pip value for this symbol
    pip_value = pips_to_points(1.0, symbol_info)
    
    # Calculate partial close threshold
    partial_close_threshold = PARTIAL_CLOSE_PIPS * pip_value
    
    # Get current price
    tick = mt5.symbol_info_tick(position.symbol)
    current_bid, current_ask = tick.bid, tick.ask
    
    # Check if position is in enough profit to trigger partial close
    if position.type == mt5.POSITION_TYPE_BUY:
        profit_pips = current_bid - position.price_open
        return profit_pips >= partial_close_threshold
    else:  # SELL position
        profit_pips = position.price_open - current_ask
        return profit_pips >= partial_close_threshold

# Move position to break-even
def move_to_break_even(position, new_sl):
    symbol_info = mt5.symbol_info(position.symbol)
    if not symbol_info:
        logger.error(f"Failed to get symbol info for {position.symbol} in move_to_break_even")
        return None

    # Normalize the new SL and existing TP to the correct number of digits
    normalized_sl = normalize_price(new_sl, symbol_info.digits)
    normalized_tp = normalize_price(position.tp, symbol_info.digits) # Normalize TP too, just in case

    # Get current prices and stop level distance
    tick = mt5.symbol_info_tick(position.symbol)
    if not tick:
        logger.error(f"Failed to get tick data for {position.symbol} in move_to_break_even")
        return None
    
    stop_level_points = symbol_info.trade_stops_level * symbol_info.point
    current_bid = tick.bid
    current_ask = tick.ask

    # --- Pre-validation Checks ---
    is_valid_sl = True
    if position.type == mt5.POSITION_TYPE_BUY:
        # For BUY, SL must be below current Bid price
        if normalized_sl >= current_bid:
            logger.warning(f"BE Check: Calculated SL {normalized_sl} is >= current Bid {current_bid} for BUY position {position.ticket}. Skipping move.")
            is_valid_sl = False
        # Check distance from Ask price (as per MT5 docs for SL modification)
        elif abs(normalized_sl - current_ask) < stop_level_points:
            logger.warning(f"BE Check: Calculated SL {normalized_sl} is too close to current Ask {current_ask} (StopLevel: {stop_level_points}) for BUY position {position.ticket}. Skipping move.")
            is_valid_sl = False
            
    elif position.type == mt5.POSITION_TYPE_SELL:
        # For SELL, SL must be above current Ask price
        if normalized_sl <= current_ask:
            logger.warning(f"BE Check: Calculated SL {normalized_sl} is <= current Ask {current_ask} for SELL position {position.ticket}. Skipping move.")
            is_valid_sl = False
        # Check distance from Bid price (as per MT5 docs for SL modification)
        elif abs(normalized_sl - current_bid) < stop_level_points:
             logger.warning(f"BE Check: Calculated SL {normalized_sl} is too close to current Bid {current_bid} (StopLevel: {stop_level_points}) for SELL position {position.ticket}. Skipping move.")
             is_valid_sl = False

    if not is_valid_sl:
        return None # Skip modification if SL is invalid

    # --- Send Request ---
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": position.symbol,
        "position": position.ticket,
        "sl": normalized_sl, # Use normalized SL
        "tp": normalized_tp, # Use normalized TP
        "magic": MAGIC
    }
    
    logger.info(f"Attempting to move position {position.ticket} to BE. Request: SL={normalized_sl}, TP={normalized_tp}")
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Error moving position {position.ticket} to break-even: {result.retcode} - {result.comment}")
        # Log more details on failure
        logger.error(f"Failed BE Request Details: Position={position.ticket}, Type={position.type}, Entry={position.price_open}, "
                     f"Attempted SL={normalized_sl}, Current Bid={current_bid}, Current Ask={current_ask}, "
                     f"StopLevel Points={stop_level_points}, Result={result}")
    else:
        logger.info(f"Position {position.ticket} moved to break-even: SL={normalized_sl}")
        
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

# Entry logic with enhanced checks
def enter_trade(direction, symbol_info, last_high, last_low, current_price):
    # Additional safety check - don't enter if we already have max positions
    positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC) or []
    if len(positions) >= MAX_POS:
        logger.warning(f"Maximum positions ({MAX_POS}) already reached. Skipping entry.")
        return
        
    # Validate that price is actually above pivot high for buys or below pivot low for sells
    if direction == 'bull' and current_price <= last_high:
        logger.warning(f"Buy signal rejected: Current price ({current_price}) not above pivot high ({last_high})")
        return
        
    if direction == 'bear' and current_price >= last_low:
        logger.warning(f"Sell signal rejected: Current price ({current_price}) not below pivot low ({last_low})")
        return
    
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, LOOKBACK)
    atr = calculate_atr(rates, ATR_PERIOD)
    tick = mt5.symbol_info_tick(SYMBOL)
    buffer_points = pips_to_points(BREAK_BUFFER_PIPS, symbol_info)

    if direction == 'bull':
        price = tick.ask
        tp = price + atr * ATR_MULT_TP
        order_type = mt5.ORDER_TYPE_BUY
        if USE_DYNAMIC_SL and last_low is not None:
            sl = last_low - buffer_points
            logger.info(f"Using dynamic SL for BUY based on last low: {last_low}")
        else:
            sl = price - atr * ATR_MULT_SL
            logger.info(f"Using ATR-based SL for BUY")
    else:  # direction == 'bear'
        price = tick.bid
        tp = price - atr * ATR_MULT_TP
        order_type = mt5.ORDER_TYPE_SELL
        if USE_DYNAMIC_SL and last_high is not None:
            sl = last_high + buffer_points
            logger.info(f"Using dynamic SL for SELL based on last high: {last_high}")
        else:
            sl = price + atr * ATR_MULT_SL
            logger.info(f"Using ATR-based SL for SELL")

    # Ensure SL is valid
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
    
    # Normalize price, SL and TP to correct digits
    normalized_price = normalize_price(price, symbol_info.digits)
    normalized_sl = normalize_price(sl, symbol_info.digits)
    normalized_tp = normalize_price(tp, symbol_info.digits)
            
    request = {
        'action': mt5.TRADE_ACTION_DEAL,
        'symbol': SYMBOL,
        'volume': LOT_SIZE,
        'type': order_type,
        'price': normalized_price,
        'sl': normalized_sl,
        'tp': normalized_tp,
        'magic': MAGIC,
        'comment': 'market structure bot',
        'type_filling': mt5.ORDER_FILLING_FOK,
    }
    result = mt5.order_send(request)
    logger.info(f"OrderSend result: {result}")

# Main bot loop with enhanced multi-timeframe confirmation
def run(stop_event):
    logger.info("Bot starting...")
    if not mt5.initialize():
        logger.error("MT5 initialization failed")
        return
    
    # Ensure symbol is selected before getting info
    if not mt5.symbol_select(SYMBOL, True):
        logger.error(f"Failed to select symbol {SYMBOL}")
        mt5.shutdown()
        return
    
    symbol_info = mt5.symbol_info(SYMBOL)
    if not symbol_info:
        logger.error(f"Failed to get symbol info for {SYMBOL}")
        mt5.shutdown()
        return
    
    while not stop_event.is_set():
        try:
            # Check existing positions for break-even and partial close
            positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC) or []
            
            # Money management - Process in order: first break-even, then partial close
            for position in positions:
                # First check if break-even can be applied
                new_sl = check_break_even(position, symbol_info)
                if new_sl:
                    result = move_to_break_even(position, new_sl)
                    # After applying break-even, wait until next cycle to check partial close
                    # This ensures the break-even is registered in the system
                    continue
                    
                # Only check partial close if break-even wasn't just applied
                if check_partial_close(position, symbol_info):
                    partial_close(position)
            
            # --- Market Structure Analysis ---
            dir_map = {}
            pivot_map = {}
            bull_count = 0
            bear_count = 0
            trade_direction = None
            triggering_tfs = []
            last_high_for_trade = None
            last_low_for_trade = None
            current_price = None

            for name, tf in zip(TIMEFRAME_NAMES, TIMEFRAMES):
                bars = mt5.copy_rates_from_pos(SYMBOL, tf, 0, LOOKBACK)
                # Ensure bars is a list even if empty
                if bars is None:
                    logger.warning(f"Could not retrieve bars for {SYMBOL} on {name}. Skipping timeframe.")
                    bars = []
                
                # Need at least PIVOT_DEPTH * 2 + 1 bars to find pivots reliably
                if len(bars) < (PIVOT_DEPTH * 2 + 1):
                    logger.debug(f"Not enough bars ({len(bars)}) on {name} for pivot depth {PIVOT_DEPTH}. Skipping.")
                    highs, lows = [], []
                    direction = None
                else:
                    highs, lows = find_pivots(bars)
                    direction = check_break(bars, highs, lows, symbol_info)
                    
                    # Get current price for entry validation
                    if not current_price and len(bars) > 0:
                        current_price = bars[0]['close']
                
                dir_map[name] = direction
                pivot_map[name] = (highs, lows)

                # Count timeframes confirming each direction
                if direction == 'bull':
                    bull_count += 1
                    triggering_tfs.append(name)
                    if not last_high_for_trade and highs:
                        last_high_for_trade = highs[-1][1]
                    if not last_low_for_trade and lows:
                        last_low_for_trade = lows[-1][1]
                elif direction == 'bear':
                    bear_count += 1
                    triggering_tfs.append(name)
                    if not last_high_for_trade and highs:
                        last_high_for_trade = highs[-1][1]
                    if not last_low_for_trade and lows:
                        last_low_for_trade = lows[-1][1]

            # Determine overall direction based on multi-timeframe confirmation
            if bull_count >= MIN_TF_CONFIRMATION:
                trade_direction = 'bull'
                logger.info(f"Bullish structure confirmed on {bull_count} timeframes: {', '.join(triggering_tfs[:MIN_TF_CONFIRMATION])}")
            elif bear_count >= MIN_TF_CONFIRMATION:
                trade_direction = 'bear'
                logger.info(f"Bearish structure confirmed on {bear_count} timeframes: {', '.join(triggering_tfs[:MIN_TF_CONFIRMATION])}")
            else:
                logger.debug(f"Insufficient timeframe confirmation: Bull={bull_count}, Bear={bear_count}, Required={MIN_TF_CONFIRMATION}")
                
            # --- Trade Entry Logic ---
            # Re-fetch positions in case partial close reduced count
            current_positions = mt5.positions_get(symbol=SYMBOL, magic=MAGIC) or []
            position_count = len(current_positions)

            # Condition: Multi-timeframe confirmation, direction confirmed, valid price level, and position limit not reached
            if trade_direction and position_count < MAX_POS:
                if trade_direction == 'bull' and current_price > last_high_for_trade:
                    logger.info(f"Attempting BUY trade entry based on {MIN_TF_CONFIRMATION}+ timeframe confirmation. Price ({current_price}) > Pivot High ({last_high_for_trade})")
                    enter_trade(trade_direction, symbol_info, last_high_for_trade, last_low_for_trade, current_price)
                elif trade_direction == 'bear' and current_price < last_low_for_trade:
                    logger.info(f"Attempting SELL trade entry based on {MIN_TF_CONFIRMATION}+ timeframe confirmation. Price ({current_price}) < Pivot Low ({last_low_for_trade})")
                    enter_trade(trade_direction, symbol_info, last_high_for_trade, last_low_for_trade, current_price)
                else:
                    logger.info(f"Trade direction ({trade_direction}) confirmed but price ({current_price}) not beyond pivot point yet.")
            elif trade_direction:
                logger.info(f"Structure shift ({trade_direction.upper()}) detected with {MIN_TF_CONFIRMATION}+ timeframe confirmation, but max positions ({position_count}/{MAX_POS}) reached. No new entry.")
            
        except Exception as e:
            logger.error(f"Error in main bot loop: {e}", exc_info=True)
            # Optional: Add a small delay after an error to prevent rapid looping on persistent issues
            time.sleep(5) 
            
        # Wait for the next cycle
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