document.addEventListener('DOMContentLoaded', function() {
    // Set default date values (January 1st of last year to today)
    const today = new Date();
    const lastYear = new Date();
    lastYear.setFullYear(today.getFullYear() - 1);
    lastYear.setMonth(0); // January
    lastYear.setDate(1);  // 1st day
    
    const startDateInput = document.getElementById('backtest-start-date');
    const endDateInput = document.getElementById('backtest-end-date');
    
    if (startDateInput && endDateInput) {
        startDateInput.valueAsDate = lastYear;
        endDateInput.valueAsDate = today;
        
        // Add event listener for the run backtest button
        const runButton = document.getElementById('run-backtest-button');
        if (runButton) {
            runButton.addEventListener('click', runBacktest);
        }
    }
});

function runBacktest() {
    const startDate = document.getElementById('backtest-start-date').value;
    const endDate = document.getElementById('backtest-end-date').value;
    
    if (!startDate || !endDate) {
        alert('Please select both start and end dates');
        return;
    }
    
    // Show loading indicator
    document.getElementById('backtest-loading').classList.remove('hidden');
    document.getElementById('backtest-results').classList.add('hidden');
    
    // Send backtest request
    fetch('/api/backtest', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            start_date: startDate,
            end_date: endDate
        }),
    })
    .then(response => response.json())
    .then(data => {
        // Hide loading indicator
        document.getElementById('backtest-loading').classList.add('hidden');
        
        if (data.success) {
            displayBacktestResults(data);
        } else {
            alert('Backtest failed: ' + data.message);
        }
    })
    .catch(error => {
        document.getElementById('backtest-loading').classList.add('hidden');
        console.error('Error running backtest:', error);
        alert('Error running backtest. See console for details.');
    });
}

function displayBacktestResults(data) {
    // Show results container
    document.getElementById('backtest-results').classList.remove('hidden');
    
    // Update summary metrics
    document.getElementById('total-trades').textContent = data.total_trades;
    document.getElementById('win-rate').textContent = data.win_rate + '%';
    document.getElementById('profit-factor').textContent = data.profit_factor;
    document.getElementById('total-profit').textContent = formatCurrency(data.total_profit);
    
    // Update detailed metrics
    document.getElementById('winning-trades').textContent = data.winning_trades;
    document.getElementById('losing-trades').textContent = data.losing_trades;
    document.getElementById('avg-win').textContent = formatCurrency(data.avg_win);
    document.getElementById('avg-loss').textContent = formatCurrency(data.avg_loss);
    document.getElementById('max-drawdown').textContent = data.max_drawdown + '%';
    document.getElementById('final-balance').textContent = formatCurrency(data.final_balance);
    
    // Generate trade list
    const tradeList = document.getElementById('trade-list');
    tradeList.innerHTML = ''; // Clear existing trade rows
    
    data.trades.forEach(trade => {
        const row = document.createElement('tr');
        const pnlClass = trade.profit > 0 ? 'text-green-600' : 'text-red-600';
        
        row.innerHTML = `
            <td class="px-4 py-2 text-sm">${trade.entry_time}</td>
            <td class="px-4 py-2 text-sm">${trade.exit_time}</td>
            <td class="px-4 py-2 text-sm">${trade.type}</td>
            <td class="px-4 py-2 text-sm">${trade.entry.toFixed(5)}</td>
            <td class="px-4 py-2 text-sm">${trade.exit.toFixed(5)}</td>
            <td class="px-4 py-2 text-sm font-medium ${pnlClass}">${formatCurrency(trade.profit)}</td>
            <td class="px-4 py-2 text-sm">${trade.reason}</td>
        `;
        
        tradeList.appendChild(row);
    });
    
    // Render equity chart
    renderEquityChart(data.equity_curve);
}

function formatCurrency(value) {
    // Format number as currency
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function renderEquityChart(equityCurve) {
    const chartElement = document.getElementById('equity-chart');
    
    // Clear any existing chart
    while (chartElement.firstChild) {
        chartElement.removeChild(chartElement.firstChild);
    }
    
    // Create a canvas for the chart
    const canvas = document.createElement('canvas');
    chartElement.appendChild(canvas);
    
    // Extract data for the chart
    const times = equityCurve.map(point => point.time);
    const values = equityCurve.map(point => point.equity);
    
    // Create chart using Chart.js
    new Chart(canvas, {
        type: 'line',
        data: {
            labels: times,
            datasets: [{
                label: 'Account Equity',
                data: values,
                borderColor: 'rgb(59, 130, 246)',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return formatCurrency(context.parsed.y);
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    ticks: {
                        maxTicksLimit: 8,
                        maxRotation: 0
                    }
                },
                y: {
                    display: true,
                    ticks: {
                        callback: function(value) {
                            return formatCurrency(value);
                        }
                    }
                }
            }
        }
    });
}
