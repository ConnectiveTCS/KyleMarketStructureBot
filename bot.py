import time
import json
import threading
import MetaTrader5 as mt5

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

# Entry logic with ATR-based SL/TP
def enter_trade(direction, symbol_info, last_high, last_low):
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, LOOKBACK)
    atr = calculate_atr(rates, ATR_PERIOD)
    tick = mt5.symbol_info_tick(SYMBOL)
    if direction == 'bull':
        price = tick.ask
        sl = price - atr * ATR_MULT_SL
        tp = price + atr * ATR_MULT_TP
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + atr * ATR_MULT_SL
        tp = price - atr * ATR_MULT_TP
        order_type = mt5.ORDER_TYPE_SELL

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
    print(f"OrderSend result: {result}")

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
    while not stop_event.is_set():
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
            highs, lows = pivot_map[trigger]
            last_high = highs[-1][1] if highs else None
            last_low  = lows[-1][1]  if lows  else None
            enter_trade(direction, symbol_info, last_high, last_low)

        time.sleep(UPDATE_INTERVAL)

    mt5.shutdown()

# Allow running from script
if __name__ == '__main__':
    stop_flag = threading.Event()
    try:
        run(stop_flag)
    except KeyboardInterrupt:
        stop_flag.set()