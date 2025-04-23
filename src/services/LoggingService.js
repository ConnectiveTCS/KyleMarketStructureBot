class LoggingService {
  constructor() {
    this.errorLogs = [];
    this.tradeLogs = [];
    this.maxLogs = 100; // Maximum number of logs to keep
    this.listeners = [];
  }

  // Add an error log
  logError(message, error = null) {
    const logEntry = {
      timestamp: new Date(),
      message,
      error: error ? error.toString() : null,
      stack: error?.stack
    };
    this.errorLogs.unshift(logEntry);
    this._trimLogs(this.errorLogs);
    this._notifyListeners();
  }

  // Add a trade issue log
  logTradeIssue(message, details = null) {
    const logEntry = {
      timestamp: new Date(),
      message,
      details
    };
    this.tradeLogs.unshift(logEntry);
    this._trimLogs(this.tradeLogs);
    this._notifyListeners();
  }

  // Keep logs under the maximum size
  _trimLogs(logArray) {
    if (logArray.length > this.maxLogs) {
      logArray.length = this.maxLogs;
    }
  }

  // Get all error logs
  getErrorLogs() {
    return [...this.errorLogs];
  }

  // Get all trade issue logs
  getTradeLogs() {
    return [...this.tradeLogs];
  }

  // Subscribe for log updates
  subscribe(callback) {
    this.listeners.push(callback);
    return () => {
      this.listeners = this.listeners.filter(listener => listener !== callback);
    };
  }

  // Notify all listeners of changes
  _notifyListeners() {
    this.listeners.forEach(listener => listener());
  }

  // Clear all logs
  clearLogs() {
    this.errorLogs = [];
    this.tradeLogs = [];
    this._notifyListeners();
  }
}

// Create a singleton instance
const loggingService = new LoggingService();
export default loggingService;
