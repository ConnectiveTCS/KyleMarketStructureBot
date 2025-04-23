document.addEventListener('DOMContentLoaded', function() {
    console.log('Initializing logging system...'); // Debug logging
    
    // Cache DOM elements
    const errorLogsContainer = document.getElementById('error-logs');
    const tradeLogsContainer = document.getElementById('trade-logs');
    const clearLogsButton = document.getElementById('clear-logs');
    
    if (!errorLogsContainer || !tradeLogsContainer || !clearLogsButton) {
        console.error('Logging containers or buttons not found in the DOM');
        return;
    }
    
    console.log('Logging DOM elements found');
    
    // Log storage
    const logs = {
        errors: [],
        trades: []
    };
    
    const maxLogs = 100; // Maximum number of logs to keep
    
    // Add an error log
    function logError(message, error = null) {
        console.log(`Logging error: ${message}`); // Debug logging
        
        const logEntry = {
            timestamp: new Date(),
            message,
            error: error ? String(error) : null
        };
        
        logs.errors.unshift(logEntry);
        trimLogs(logs.errors);
        renderLogs();
    }
    
    // Add a trade issue log
    function logTradeIssue(message, details = null) {
        console.log(`Logging trade issue: ${message}`); // Debug logging
        
        const logEntry = {
            timestamp: new Date(),
            message,
            details: details ? JSON.stringify(details, null, 2) : null
        };
        
        logs.trades.unshift(logEntry);
        trimLogs(logs.trades);
        renderLogs();
    }
    
    // Keep logs under the maximum size
    function trimLogs(logArray) {
        if (logArray.length > maxLogs) {
            logArray.length = maxLogs;
        }
    }
    
    // Clear all logs
    function clearLogs() {
        logs.errors = [];
        logs.trades = [];
        renderLogs();
    }
    
    // Render logs to their containers
    function renderLogs() {
        try {
            // Render error logs
            if (logs.errors.length === 0) {
                errorLogsContainer.innerHTML = '<div class="text-center text-gray-500 py-6">No error logs to display</div>';
            } else {
                errorLogsContainer.innerHTML = logs.errors.map(log => createLogItemHTML(log, 'error')).join('');
            }
            
            // Render trade logs
            if (logs.trades.length === 0) {
                tradeLogsContainer.innerHTML = '<div class="text-center text-gray-500 py-6">No trade issue logs to display</div>';
            } else {
                tradeLogsContainer.innerHTML = logs.trades.map(log => createLogItemHTML(log, 'trade')).join('');
            }
        } catch (e) {
            console.error('Error rendering logs:', e);
        }
    }
    
    // Create HTML for a log item
    function createLogItemHTML(log, type) {
        const timestamp = log.timestamp.toLocaleTimeString();
        let detailsHTML = '';
        
        if (type === 'error' && log.error) {
            detailsHTML = `<div class="log-details">${escapeHTML(log.error)}</div>`;
        } else if (type === 'trade' && log.details) {
            detailsHTML = `<div class="log-details">${escapeHTML(log.details)}</div>`;
        }
        
        return `
            <div class="log-item log-${type}">
                <span class="log-timestamp">${timestamp}</span>
                <span class="log-message">${escapeHTML(log.message)}</span>
                ${detailsHTML}
            </div>
        `;
    }
    
    // Escape HTML to prevent XSS
    function escapeHTML(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
    
    // Event listeners
    clearLogsButton.addEventListener('click', clearLogs);
    
    // Add initial logs for testing visibility
    logError('Logging system initialized', 'This is a test error message');
    logTradeIssue('Trade system ready', { status: 'online', time: new Date().toISOString() });
    
    // Add some more logs after a delay to ensure they appear
    setTimeout(() => {
        logError('Test error after delay', 'This confirms the logging system is working');
        logTradeIssue('Trade placement test', { symbol: 'AAPL', price: 150.25, quantity: 10 });
    }, 2000);
    
    // Auto update logs every second
    setInterval(renderLogs, 1000);
    
    // Expose logging functions globally for use by other scripts
    window.systemLogger = {
        logError,
        logTradeIssue,
        clearLogs
    };
    
    // Initial render
    renderLogs();
    
    console.log('Logging system initialized successfully');
});
