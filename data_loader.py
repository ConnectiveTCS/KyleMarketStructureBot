# ...existing code...

def load_all_timeframes(symbol, timeframes=['M1', 'M5', 'M15', 'H1', 'H4', 'D1']):
    """Load data for all timeframes."""
    data = {}
    
    for timeframe in timeframes:
        try:
            data[timeframe] = load_timeframe_data(symbol, timeframe)
            # Add debug logging
            print(f"Loaded {len(data[timeframe])} records for {timeframe}")
        except Exception as e:
            print(f"Error loading {timeframe}: {str(e)}")
            # Initialize with empty data rather than omitting
            data[timeframe] = []
    
    return data

# ...existing code...
