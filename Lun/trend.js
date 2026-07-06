/**
 * Trend chart management with dynamic metric switching via AJAX
 */

// Global trend chart instance
let trendChart = null;

// Current selection, kept in sync so switching one selector preserves the other
let currentMetric = null;
let currentColor = null;
let currentLabel = null;

const PERIOD_LABELS = {
    '7': '7 days',
    '30': '30 days',
    '90': '90 days',
    '120': '120 days',
    '365': '1 year',
    'all': 'all time'
};

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
        currentMetric = metric;
        currentColor = color;
        currentLabel = label;

        // Fetch new trend data from API
        const days = (typeof TREND_DAYS !== 'undefined') ? TREND_DAYS : 90;
        const response = await fetch(`/discrepancies/api/trend/?metric=${metric}&days=${days}`);

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
 * Initialize metric and period selector event listeners
 */
document.addEventListener('DOMContentLoaded', function() {
    const metricSelector = document.getElementById('metric-selector');
    const periodSelector = document.getElementById('period-selector');
    const periodLabel = document.getElementById('trend-period-label');

    if (metricSelector) {
        const initialOption = metricSelector.selectedOptions[0];
        currentMetric = initialOption.dataset.metric;
        currentColor = initialOption.dataset.color;
        currentLabel = initialOption.text;

        metricSelector.addEventListener('change', function(e) {
            const selectedOption = e.target.selectedOptions[0];
            updateTrendChart(selectedOption.dataset.metric, selectedOption.dataset.color, selectedOption.text);
        });
    }

    if (periodSelector) {
        periodSelector.addEventListener('change', function(e) {
            TREND_DAYS = e.target.value;
            if (periodLabel) {
                periodLabel.textContent = `(${PERIOD_LABELS[TREND_DAYS] || TREND_DAYS + ' days'})`;
            }
            updateTrendChart(currentMetric, currentColor, currentLabel);
        });
    }
});
