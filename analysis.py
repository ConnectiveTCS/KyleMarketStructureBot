# ...existing code...

def analyze_market_structure(data, timeframes=['M1', 'M5', 'M15', 'H1', 'H4', 'D1']):
    """Analyze market structure across multiple timeframes."""
    results = {}
    
    for timeframe in timeframes:
        if timeframe in data:
            # Make sure we have enough data for this timeframe
            if len(data[timeframe]) > 10:  # Ensure minimum data points
                results[timeframe] = determine_market_structure(data[timeframe])
            else:
                results[timeframe] = "none"
        else:
            results[timeframe] = "none"
    
    return results

def determine_market_structure(timeframe_data):
    """Determine if market structure is bullish or bearish."""
    # ...existing code...
    
    # Make sure we're returning a value for every timeframe
    # This should return "Bull", "Bear", or "none" for each timeframe
    # Ensure the logic here works correctly
    
    # ...existing code...
