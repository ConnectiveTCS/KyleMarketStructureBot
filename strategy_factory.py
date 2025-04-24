from strategies import get_strategy_class, get_available_strategies

class StrategyFactory:
    """Factory class for creating and managing trading strategies"""
    
    @staticmethod
    def create_strategy(config, symbol):
        """Create a strategy instance based on the configuration"""
        strategy_name = config.get("active_strategy", "market_structure")
        strategy_class = get_strategy_class(strategy_name)
        return strategy_class(config, symbol)
    
    @staticmethod
    def get_available_strategies():
        """Get a list of available strategies"""
        return get_available_strategies()
    
    @staticmethod
    def get_strategy_params(strategy_name):
        """Get the parameters for a specific strategy"""
        strategies = get_available_strategies()
        return strategies.get(strategy_name, {}).get("params", {})
    
    @staticmethod
    def validate_config_for_strategy(config, strategy_name):
        """Validate the configuration for a specific strategy"""
        required_params = StrategyFactory.get_strategy_params(strategy_name)
        missing_params = []
        
        for param in required_params:
            if param not in config:
                missing_params.append(param)
        
        return {
            "valid": len(missing_params) == 0,
            "missing_params": missing_params
        }
