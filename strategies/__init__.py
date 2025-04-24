from strategies.base_strategy import BaseStrategy
from strategies.market_structure_strategy import MarketStructureStrategy
from strategies.stochastic_strategy import StochasticStrategy

# Dictionary of available strategies
AVAILABLE_STRATEGIES = {
    "market_structure": MarketStructureStrategy,
    "stochastic": StochasticStrategy
}

def get_strategy_class(strategy_name):
    """Get the strategy class for the given strategy name"""
    return AVAILABLE_STRATEGIES.get(strategy_name, MarketStructureStrategy)

def get_available_strategies():
    """Get a dictionary of available strategies with their descriptions"""
    strategies = {}
    for name, strategy_class in AVAILABLE_STRATEGIES.items():
        strategies[name] = {
            "name": name,
            "description": strategy_class.get_strategy_description(),
            "params": strategy_class.get_required_config_params()
        }
    return strategies
