/**
 * Gauge creation and management utilities using Chart.js
 */

/**
 * Get the appropriate color based on value and thresholds
 * @param {number} value - Current value (0-100)
 * @param {object} thresholds - Threshold values {critical, warning, good}
 * @param {object} colors - Color values {critical, warning, good}
 * @returns {string} Hex color code
 */
function getColorForValue(value, thresholds, colors) {
    if (value >= thresholds.good) return colors.good;
    if (value >= thresholds.warning) return colors.warning;
    return colors.critical;
}

/**
 * Create a gauge chart (semi-circular doughnut)
 * @param {string} canvasId - ID of the canvas element
 * @param {number} value - Value to display (0-100)
 * @param {object} thresholds - Threshold configuration
 * @param {object} colors - Color configuration
 * @param {boolean} isLarge - Whether this is a large hero gauge
 * @returns {Chart} Chart.js instance
 */
/**
 * Initialize tooltips on gauge cards with a 1-second hover delay.
 */
function initGaugeTooltips() {
    const cards = document.querySelectorAll('[data-info]');
    cards.forEach(card => {
        const tooltip = card.querySelector('.gauge-tooltip');
        if (!tooltip) return;

        let timer = null;

        card.addEventListener('mouseenter', () => {
            timer = setTimeout(() => {
                tooltip.classList.add('visible');
            }, 1000);
        });

        card.addEventListener('mouseleave', () => {
            clearTimeout(timer);
            tooltip.classList.remove('visible');
        });
    });
}

document.addEventListener('DOMContentLoaded', initGaugeTooltips);

function createGauge(canvasId, value, thresholds, colors, isLarge = false) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const gaugeColor = getColorForValue(value, thresholds, colors);
    
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [value, 100 - value],
                backgroundColor: [gaugeColor, 'rgba(128, 128, 128, 0.1)'],
                borderWidth: 0,
                circumference: 180,
                rotation: 270
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            cutout: isLarge ? '75%' : '70%',
            plugins: {
                tooltip: { enabled: false },
                legend: { display: false }
            }
        }
    });
}
