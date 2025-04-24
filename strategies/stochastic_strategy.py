from strategies.base_strategy import BaseStrategy
import numpy as np

class StochasticStrategy(BaseStrategy):
    """Stochastic Oscillator scalping strategy implementation"""
    
    def __init__(self, config, symbol):
        super().__init__(config, symbol)
        self.name = "Stochastic Oscillator"
        self.description = "Scalping strategy based on Stochastic Oscillator crossovers"
        
        # Strategy-specific initialization
        self.k_period = config.get("stoch_k_period", 5)
        self.d_period = config.get("stoch_d_period", 3)
        self.slowing = config.get("stoch_slowing", 3)
        self.overbought_level = config.get("stoch_overbought", 80)
        self.oversold_level = config.get("stoch_oversold", 20)
        self.trend_detection = config.get("stoch_trend_detection", "SMA")
        self.trend_period = config.get("stoch_trend_period", 50)
    
    def calculate_stochastic(self, high_prices, low_prices, close_prices):
        """Calculate Stochastic Oscillator values (%K and %D)"""
        # Initialize %K and %D arrays
        k_values = np.zeros_like(close_prices)
        d_values = np.zeros_like(close_prices)
        
        # Calculate %K
        for i in range(self.k_period - 1, len(close_prices)):
            highest_high = np.max(high_prices[i - self.k_period + 1:i + 1])
            lowest_low = np.min(low_prices[i - self.k_period + 1:i + 1])
            
            # Avoid division by zero
            if highest_high - lowest_low == 0:
                k_values[i] = 50  # Neutral value
            else:
                k_values[i] = 100 * (close_prices[i] - lowest_low) / (highest_high - lowest_low)
        
        # Apply slowing if specified
        if self.slowing > 1:
            smoothed_k = np.zeros_like(k_values)
            for i in range(self.k_period + self.slowing - 2, len(k_values)):
                smoothed_k[i] = np.mean(k_values[i - self.slowing + 1:i + 1])
            k_values = smoothed_k
        
        # Calculate %D (SMA of %K)
        for i in range(self.k_period + self.d_period - 2, len(k_values)):
            d_values[i] = np.mean(k_values[i - self.d_period + 1:i + 1])
        
        return k_values, d_values
    
    def detect_trend(self, close_prices):
        """Detect market trend using specified method"""
        if self.trend_detection == "SMA":
            if len(close_prices) > self.trend_period:
                sma = np.mean(close_prices[-self.trend_period:])
                current_price = close_prices[-1]
                
                if current_price > sma:
                    return "uptrend"
                elif current_price < sma:
                    return "downtrend"
        
        # Default to neutral if no trend is detected or not enough data
        return "neutral"
    
    def calculate_signals(self, data):
        """Calculate trading signals based on Stochastic Oscillator"""
        # Extract price data
        high_prices = np.array(data.get("high", []))
        low_prices = np.array(data.get("low", []))
        close_prices = np.array(data.get("close", []))
        
        if len(close_prices) < self.k_period + self.d_period:
            return {
                "market_direction": None,
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None,
                "stoch_k": None,
                "stoch_d": None,
                "trend": None,
                "signal": None
            }
        
        # Calculate Stochastic Oscillator values
        k_values, d_values = self.calculate_stochastic(high_prices, low_prices, close_prices)
        
        # Detect trend
        trend = self.detect_trend(close_prices)
        
        # Get most recent values
        current_k = k_values[-1]
        current_d = d_values[-1]
        prev_k = k_values[-2] if len(k_values) > 1 else None
        prev_d = d_values[-2] if len(d_values) > 1 else None
        
        # Initialize signal
        signal = None
        market_direction = None
        entry_price = None
        stop_loss = None
        take_profit = None
        
        # Check for crossovers
        if prev_k is not None and prev_d is not None:
            # Bullish crossover (K crosses above D)
            if prev_k < prev_d and current_k > current_d:
                if trend == "uptrend" and current_k < self.oversold_level:
                    signal = "buy"
                    market_direction = "bull"
                    entry_price = close_prices[-1]
                    stop_loss = low_prices[-1] - (self.config.get("stop_loss_pips", 5) * 0.0001)
                    take_profit = entry_price + (self.config.get("take_profit_pips", 10) * 0.0001)
            
            # Bearish crossover (K crosses below D)
            elif prev_k > prev_d and current_k < current_d:
                if trend == "downtrend" and current_k > self.overbought_level:
                    signal = "sell"
                    market_direction = "bear"
                    entry_price = close_prices[-1]
                    stop_loss = high_prices[-1] + (self.config.get("stop_loss_pips", 5) * 0.0001)
                    take_profit = entry_price - (self.config.get("take_profit_pips", 10) * 0.0001)
        
        return {
            "market_direction": market_direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "stoch_k": current_k,
            "stoch_d": current_d,
            "trend": trend,
            "signal": signal
        }
    
    def get_entry_conditions(self, data):
        """Return entry conditions for Stochastic strategy"""
        return {
            "bull": [
                "Uptrend Detected",
                "Stochastic Oversold (< 20)",
                "Bullish Crossover (K crosses above D)"
            ],
            "bear": [
                "Downtrend Detected",
                "Stochastic Overbought (> 80)",
                "Bearish Crossover (K crosses below D)"
            ]
        }
    
    def get_exit_conditions(self, data):
        """Return exit conditions for Stochastic strategy"""
        return [
            "Opposite Signal Generated",
            "Stochastic Reaches Extreme Level",
            "Take Profit Hit",
            "Stop Loss Hit"
        ]
    
    @classmethod
    def get_required_config_params(cls):
        """Return stochastic strategy configuration parameters"""
        return {
            "stoch_k_period": 5,
            "stoch_d_period": 3,
            "stoch_slowing": 3,
            "stoch_overbought": 80,
            "stoch_oversold": 20,
            "stoch_trend_detection": "SMA",
            "stoch_trend_period": 50
        }
    
    @classmethod
    def get_strategy_description(cls):
        """Return a description of the stochastic strategy"""
        return """
        Stochastic Oscillator Scalping Strategy uses the stochastic oscillator to identify 
        potential turning points in the market. It enters long positions in uptrends when the 
        %K line crosses above the %D line in oversold territory, and enters short positions 
        in downtrends when the %K line crosses below the %D line in overbought territory.
        """
