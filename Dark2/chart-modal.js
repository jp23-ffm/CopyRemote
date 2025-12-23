// static/js/chart-modal.js

// Configuration des champs - sera injecté depuis Django
let availableFields = {};

// Fonction pour initialiser avec les données Django
function initChartModal(fields) {
    availableFields = fields;
}

let chartCount = 0;
const MAX_CHARTS = 4;

function openChartModal() {
    const modal = document.getElementById('chartModal');
    const container = document.getElementById('chartSelectors');
    
    // NOUVEAU : Vider complètement le modal
    container.innerHTML = '';
    chartCount = 0;
    
    // Réafficher le bouton "Add" au cas où
    const addBtn = document.getElementById('addChartBtn');
    if (addBtn) {
        addBtn.style.display = 'block';
    }
    
    modal.classList.add('show');
    document.body.style.overflow = 'hidden';
    
    // Ajouter le premier sélecteur vide
    addChartSelector();
}

function closeChartModal() {
    const modal = document.getElementById('chartModal');
    modal.classList.remove('show');
    document.body.style.overflow = '';
}

function addChartSelector() {
    if (chartCount >= MAX_CHARTS) {
        alert('Maximum 4 charts allowed');
        return;
    }
    
    chartCount++;
    const container = document.getElementById('chartSelectors');
    const selectorId = `chart-${chartCount}`;
    
    const fieldOptions = Object.entries(availableFields)
        .map(([key, value]) => `<option value="${key}">${value.label}</option>`)
        .join('');
    
    const div = document.createElement('div');
    div.className = 'chart-selector';
    div.id = selectorId;
    div.innerHTML = `
        <div class="chart-selector-header">
            <label>Chart ${chartCount}</label>
            <button type="button" class="remove-chart" onclick="removeChartSelector('${selectorId}')">✕ Remove</button>
        </div>
        
        <label class="field-label">Field to analyze:</label>
        <select name="fields" id="field-${chartCount}" onchange="updateChartTypes(${chartCount})" ${chartCount === 1 ? 'required' : ''}>
            <option value="">-- Select a field --</option>
            ${fieldOptions}
        </select>
        
        <label class="field-label">Chart type:</label>
        <select name="types" id="type-${chartCount}" ${chartCount === 1 ? 'required' : ''}>
            <option value="">-- First select a field --</option>
        </select>
    `;
    
    container.appendChild(div);
    
    if (chartCount >= MAX_CHARTS) {
        document.getElementById('addChartBtn').style.display = 'none';
    }
}


function removeChartSelector(selectorId) {
    const container = document.getElementById('chartSelectors');
    
    // Empêcher de supprimer s'il n'y a qu'un seul sélecteur
    if (container.children.length <= 1) {
        alert('You need at least one chart');
        return;
    }
    
    document.getElementById(selectorId).remove();
    chartCount--;
    
    if (chartCount < MAX_CHARTS) {
        document.getElementById('addChartBtn').style.display = 'block';
    }
    
    // Renuméroter les sélecteurs
    const selectors = document.querySelectorAll('.chart-selector');
    chartCount = 0;
    selectors.forEach((selector, index) => {
        chartCount++;
        selector.id = `chart-${chartCount}`;
        
        const label = selector.querySelector('.chart-selector-header label');
        if (label) {
            label.textContent = `Chart ${chartCount}`;
        }
        
        const fieldSelect = selector.querySelector('select[name="fields"]');
        const typeSelect = selector.querySelector('select[name="types"]');
        const removeBtn = selector.querySelector('.remove-chart');
        
        if (fieldSelect) {
            fieldSelect.id = `field-${chartCount}`;
            fieldSelect.setAttribute('onchange', `updateChartTypes(${chartCount})`);
            // Premier champ required, les autres non
            if (chartCount === 1) {
                fieldSelect.setAttribute('required', 'required');
                typeSelect.setAttribute('required', 'required');
            } else {
                fieldSelect.removeAttribute('required');
                typeSelect.removeAttribute('required');
            }
        }
        
        if (typeSelect) {
            typeSelect.id = `type-${chartCount}`;
        }
        
        if (removeBtn) {
            removeBtn.setAttribute('onclick', `removeChartSelector('chart-${chartCount}')`);
        }
    });
}
function updateChartTypes(chartNumber) {
    const fieldSelect = document.getElementById(`field-${chartNumber}`);
    const typeSelect = document.getElementById(`type-${chartNumber}`);
    const selectedField = fieldSelect.value;
    
    if (!selectedField) {
        typeSelect.innerHTML = `
            <option value="">-- Select chart type --</option>
            <option value="pie">🥧 Pie Chart</option>
            <option value="doughnut">🍩 Donut Chart</option>
            <option value="bar">📊 Bar Chart</option>
            <option value="line">📈 Line Chart</option>
        `;
        return;
    }
    
    const suitableCharts = availableFields[selectedField].suitable_charts;
    const chartIcons = {
        'pie': '🥧',
        'doughnut': '🍩',
        'bar': '📊',
        'line': '📈'
    };
    
    const chartLabels = {
        'pie': 'Pie Chart',
        'doughnut': 'Donut Chart',
        'bar': 'Bar Chart',
        'line': 'Line Chart'
    };
    
    typeSelect.innerHTML = '<option value="">-- Select chart type --</option>' +
        suitableCharts.map(type => 
            `<option value="${type}">${chartIcons[type]} ${chartLabels[type]}</option>`
        ).join('');
}

// Event listeners
document.addEventListener('DOMContentLoaded', function() {
    // Form submit
    const chartForm = document.getElementById('chartForm');
    if (chartForm) {
        chartForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const params = new URLSearchParams(window.location.search);
            
            for (let [key, value] of params.entries()) {
                if (!key.startsWith('page')) {
                    formData.append(key, value);
                }
            }
            
            // Adapter l'URL selon ton routing Django
            const url = '/serversgroups/charts/?' + new URLSearchParams(formData).toString();
            window.open(url, '_blank');
			closeChartModal();
        });
    }
    
    // Fermer en cliquant en dehors
    const modal = document.getElementById('chartModal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeChartModal();
            }
        });
        
        const modalDialog = modal.querySelector('.modal-dialog');
        if (modalDialog) {
            modalDialog.addEventListener('click', function(e) {
                e.stopPropagation();
            });
        }
    }
    
    // Fermer avec Echap
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && modal.classList.contains('show')) {
            closeChartModal();
        }
    });
});