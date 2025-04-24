from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, config, symbol):
        self.config = config
        self.symbol = symbol
        self.name = "Base Strategy"
        self.description = "Base strategy class"
    
    @abstractmethod
    def calculate_signals(self, data):
        """Calculate trading signals based on the strategy logic"""
        pass
    
    @abstractmethod
    def get_entry_conditions(self, data):
        """Return entry conditions for the strategy"""
        pass
    
    @abstractmethod
    def get_exit_conditions(self, data):
        """Return exit conditions for the strategy"""
        pass
    
    @classmethod
    def get_required_config_params(cls):
        """Return a dictionary of required configuration parameters and their default values"""
        return {}
    
    @classmethod
    def get_strategy_description(cls):
        """Return a description of the strategy"""
        return "Base trading strategy"
    
    def get_strategy_info(self):
        """Return information about the strategy"""
        return {
            "name": self.name,
            "description": self.description,
            "params": self.get_required_config_params()
        }
