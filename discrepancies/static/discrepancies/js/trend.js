/**
 * Trend chart management with dynamic metric switching via AJAX
 */

// Global trend chart instance
let trendChart = null;

/**
 * Initialize the trend line chart with initial data
 * @param {array} labels - X-axis labels (dates)
 * @param {array} values - Y-axis values (counts)
 * @param {string} color - Line color
 * @param {string} label - Dataset label
 */
function initTrendChart(labels, values, color, label = 'Issues') {
    const ctx = document.getElementById('trend-chart').getContext('2d');
    
    trendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: values,
                borderColor: color,
                backgroundColor: color + '33', // Add transparency
                tension: 0.4,
                fill: true,
                pointRadius: 4,
                pointHoverRadius: 6
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
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        precision: 0
                    }
                }
            },
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false
            }
        }
    });
}

/**
 * Update the trend chart with new data via AJAX
 * @param {string} metric - Metric name from AnalysisSnapshot model
 * @param {string} color - New line color
 * @param {string} label - New dataset label
 */
async function updateTrendChart(metric, color, label) {
    try {
        // Fetch new trend data from API
        const response = await fetch(`/discrepancies/api/trend/?metric=${metric}`);
        
        if (!response.ok) {
            throw new Error('Failed to fetch trend data');
        }
        
        const data = await response.json();
        
        // Update chart data
        trendChart.data.labels = data.labels;
        trendChart.data.datasets[0].data = data.values;
        trendChart.data.datasets[0].borderColor = color;
        trendChart.data.datasets[0].backgroundColor = color + '33';
        trendChart.data.datasets[0].label = label;
        
        // Animate the update
        trendChart.update('active');
        
    } catch (error) {
        console.error('Error updating trend chart:', error);
    }
}

/**
 * Initialize metric selector event listener
 */
document.addEventListener('DOMContentLoaded', function() {
    const selector = document.getElementById('metric-selector');
    
    if (selector) {
        selector.addEventListener('change', function(e) {
            const selectedOption = e.target.selectedOptions[0];
            const metric = selectedOption.dataset.metric;
            const color = selectedOption.dataset.color;
            const label = selectedOption.text;
            
            updateTrendChart(metric, color, label);
        });
    }
});
