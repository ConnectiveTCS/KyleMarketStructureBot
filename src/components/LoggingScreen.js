import React, { useState, useEffect } from 'react';
import loggingService from '../services/LoggingService';

const LogItem = ({ log }) => {
  const timeString = log.timestamp.toLocaleTimeString();
  
  return (
    <div className="log-item">
      <span className="log-time">{timeString}</span>
      <span className="log-message">{log.message}</span>
      {log.details && <span className="log-details">{JSON.stringify(log.details)}</span>}
      {log.error && <span className="log-error">{log.error}</span>}
    </div>
  );
};

const LoggingScreen = () => {
  const [errorLogs, setErrorLogs] = useState([]);
  const [tradeLogs, setTradeLogs] = useState([]);
  const [activeTab, setActiveTab] = useState('errors');

  // Update logs every second
  useEffect(() => {
    const updateLogs = () => {
      setErrorLogs(loggingService.getErrorLogs());
      setTradeLogs(loggingService.getTradeLogs());
    };

    // Initial update
    updateLogs();

    // Subscribe to log changes
    const unsubscribe = loggingService.subscribe(updateLogs);
    
    // Set up interval for updating every second
    const intervalId = setInterval(updateLogs, 1000);

    return () => {
      clearInterval(intervalId);
      unsubscribe();
    };
  }, []);

  const handleClearLogs = () => {
    loggingService.clearLogs();
  };

  return (
    <div className="logging-screen">
      <div className="logging-header">
        <h2>Logging Dashboard</h2>
        <div className="tab-controls">
          <button 
            className={activeTab === 'errors' ? 'active' : ''} 
            onClick={() => setActiveTab('errors')}
          >
            Errors ({errorLogs.length})
          </button>
          <button 
            className={activeTab === 'trades' ? 'active' : ''} 
            onClick={() => setActiveTab('trades')}
          >
            Trade Issues ({tradeLogs.length})
          </button>
          <button className="clear-logs" onClick={handleClearLogs}>
            Clear Logs
          </button>
        </div>
      </div>

      <div className="logs-container">
        {activeTab === 'errors' ? (
          errorLogs.length > 0 ? (
            errorLogs.map((log, index) => <LogItem key={index} log={log} />)
          ) : (
            <div className="no-logs">No error logs to display</div>
          )
        ) : (
          tradeLogs.length > 0 ? (
            tradeLogs.map((log, index) => <LogItem key={index} log={log} />)
          ) : (
            <div className="no-logs">No trade issue logs to display</div>
          )
        )}
      </div>
    </div>
  );
};

export default LoggingScreen;
