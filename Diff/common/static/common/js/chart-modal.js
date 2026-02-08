let availableFields = {};
let chartCount = 0;
const MAX_CHARTS = 4;
 
let currentAppName = 'inventory'; 
let chartsLoaded = false;
let savedCharts = []; // Store loaded charts

function initChartModal(jsonData, appName) {
    availableFields = jsonData.fields || {};
    availableCategories = jsonData.categories || {};
    currentAppName = appName; 
}


function openChartModal() {
    const modal = document.getElementById('chartModal');
    const container = document.getElementById('chartSelectors');
    container.innerHTML = '';
    chartCount = 0;
    
    const addBtn = document.getElementById('addChartBtn');
    if (addBtn) addBtn.style.display = 'block';
    
    modal.classList.add('show');
    document.body.style.overflow = 'hidden';

    addChartSelector();
    
    // Load saved charts if not already loaded
    if (!chartsLoaded) {
        loadSavedChartsList();
    }
}


function closeChartModal() {
    const modal = document.getElementById('chartModal');
    modal.classList.remove('show');
    document.body.style.overflow = '';
    
    // Close dropdown if open
    closeSavedChartDropdown();
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
        .sort((a, b) => {
            const nameA = a[1].displayname.toUpperCase();
            const nameB = b[1].displayname.toUpperCase();
            return nameA.localeCompare(nameB);
        })
        .map(([key, value]) => `<option value="${key}">${value.displayname}</option>`)
        .join('');
           
    const showRemoveBtn = container.children.length >= 1;
    
    const div = document.createElement('div');
    div.className = 'chart-selector';
    div.id = selectorId;
    div.innerHTML = `
        <div class="chart-selector-header">
            <label>Chart ${chartCount}</label>
            ${showRemoveBtn ? `<button type="button" class="remove-chart" onclick="removeChartSelector('${selectorId}')">✕ Remove</button>` : ''}
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
    
    if (container.children.length === 2) {
        const firstChart = container.children[0];
        const firstHeader = firstChart.querySelector('.chart-selector-header');
        if (firstHeader && !firstHeader.querySelector('.remove-chart')) {
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'remove-chart';
            removeBtn.textContent = '✕ Remove';
            removeBtn.onclick = () => removeChartSelector('chart-1');
            firstHeader.appendChild(removeBtn);
        }
    }
    
    if (chartCount >= MAX_CHARTS) {
        document.getElementById('addChartBtn').style.display = 'none';
    }
}


function removeChartSelector(selectorId) {
    const container = document.getElementById('chartSelectors');
    if (container.children.length <= 1) return;
    
    document.getElementById(selectorId).remove();
    chartCount--;
    
    if (container.children.length === 1) {
        const lastChart = container.children[0];
        const removeBtn = lastChart.querySelector('.remove-chart');
        if (removeBtn) removeBtn.remove();
    }
    
    if (chartCount < MAX_CHARTS) {
        document.getElementById('addChartBtn').style.display = 'block';
    }
    
    const selectors = document.querySelectorAll('.chart-selector');
    chartCount = 0;
    selectors.forEach((selector, index) => {
        chartCount++;
        selector.id = `chart-${chartCount}`;
        
        const label = selector.querySelector('.chart-selector-header label');
        if (label) label.textContent = `Chart ${chartCount}`;
        
        const fieldSelect = selector.querySelector('select[name="fields"]');
        const typeSelect = selector.querySelector('select[name="types"]');
        const removeBtn = selector.querySelector('.remove-chart');
        
        if (fieldSelect) {
            fieldSelect.id = `field-${chartCount}`;
            fieldSelect.setAttribute('onchange', `updateChartTypes(${chartCount})`);
            if (chartCount === 1) {
                fieldSelect.setAttribute('required', 'required');
                typeSelect.setAttribute('required', 'required');
            } else {
                fieldSelect.removeAttribute('required');
                typeSelect.removeAttribute('required');
            }
        }
        
        if (typeSelect) typeSelect.id = `type-${chartCount}`;
        if (removeBtn) removeBtn.setAttribute('onclick', `removeChartSelector('chart-${chartCount}')`);
    });
}


function updateChartTypes(chartNumber) {
    const fieldSelect = document.getElementById(`field-${chartNumber}`);
    const typeSelect = document.getElementById(`type-${chartNumber}`);
    const selectedField = fieldSelect.value;
    
    if (!selectedField) {
        typeSelect.innerHTML = '<option value="">-- First select a field --</option>';
        return;
    }
    
    const suitableCharts = ['pie', 'bar', 'doughnut', 'line'];
    const chartIcons = { 'pie': '🥧', 'doughnut': '🍩', 'bar': '📊', 'line': '📈' };
    const chartLabels = { 'pie': 'Pie Chart', 'doughnut': 'Donut Chart', 'bar': 'Bar Chart', 'line': 'Line Chart' };
    
    typeSelect.innerHTML = '<option value="">-- Select chart type --</option>' +
        suitableCharts.map(type => `<option value="${type}">${chartIcons[type]} ${chartLabels[type]}</option>`).join('');
}


// ============================================
// CUSTOM DROPDOWN FUNCTIONS
// ============================================

function toggleSavedChartDropdown() {
    const dropdown = document.getElementById('savedChartDropdown');
    const button = document.getElementById('savedChartButton');
    
    if (dropdown.classList.contains('show')) {
        closeSavedChartDropdown();
    } else {
        dropdown.classList.add('show');
        button.classList.add('open');
        
        // Always reload the list when opening (to catch new saves)
        loadSavedChartsList();
    }
}

function closeSavedChartDropdown() {
    const dropdown = document.getElementById('savedChartDropdown');
    const button = document.getElementById('savedChartButton');
    
    dropdown.classList.remove('show');
    button.classList.remove('open');
}

// Load the saved charts
async function loadSavedChartsList() {
    try {
        const response = await fetch(`/common/api/charts/list/?app=${currentAppName}`);
        
        if (!response.ok) {
            console.error('HTTP error:', response.status);
            return;
        }
        
        const data = await response.json();
        const listContainer = document.getElementById('savedChartList');
        
        if (!listContainer) return;
        
        if (data.success && Array.isArray(data.charts) && data.charts.length > 0) {
            savedCharts = data.charts;
            
            // Build the list
            listContainer.innerHTML = '';
            
            data.charts.forEach(chart => {
                const item = document.createElement('div');
                item.className = 'saved-chart-item';
                item.dataset.chartId = chart.id;
                item.dataset.filters = JSON.stringify(chart.filters);
                
                item.innerHTML = `
                    <span class="saved-chart-item-name">${chart.name}</span>
                    <button class="saved-chart-delete" onclick="deleteSavedChart(${chart.id}, event)" title="Delete this view">
                        ✕
                    </button>
                `;
                
                // Click on item name to load
                item.querySelector('.saved-chart-item-name').addEventListener('click', function(e) {
                    e.stopPropagation();
                    loadSavedChart(chart.id);
                });
                
                listContainer.appendChild(item);
            });
            
            chartsLoaded = true;
        } else {
            listContainer.innerHTML = '<div class="saved-chart-empty">(No saved views yet)</div>';
            chartsLoaded = true;
        }
        
    } catch (error) {
        console.error('Error loading saved charts:', error);
        const listContainer = document.getElementById('savedChartList');
        if (listContainer) {
            listContainer.innerHTML = '<div class="saved-chart-empty">Error loading views</div>';
        }
    }
}


function loadSavedChart(chartId) {
    const chart = savedCharts.find(c => c.id === chartId);
    if (!chart) return;
    
    const filters = chart.filters;
    const params = new URLSearchParams();
    
    if (filters.fields) {
        filters.fields.forEach(field => params.append('fields', field));
    }
    if (filters.types) {
        filters.types.forEach(type => params.append('types', type));
    }
    
    Object.entries(filters).forEach(([key, value]) => {
        if (key !== 'fields' && key !== 'types') {
            params.append(key, value);
        }
    });
    
    const url = `/${currentAppName}/charts/?${params.toString()}`;
    window.open(url, '_blank');
    
    // Close dropdown
    closeSavedChartDropdown();
}


// Delete a saved chart
async function deleteSavedChart(chartId, event) {
    event.stopPropagation(); // Prevent loading the chart
    
    const chart = savedCharts.find(c => c.id === chartId);
    if (!chart) return;
    
    if (!confirm(`Delete "${chart.name}"?`)) return;
    
    try {
        const response = await fetch(`/common/api/charts/${chartId}/delete/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            }
        });
        
        const data = await response.json();
        if (data.success) {
            // Reload the list
            chartsLoaded = false;
            loadSavedChartsList();
            
            showSimpleToast(`View "${chart.name}" deleted`);
        } else {
            alert('Error: ' + data.error);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('Error deleting view');
    }
}


function showSimpleToast(message) {
    const toast = document.createElement('div');
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: var(--btn-success);
        color: white;
        padding: 12px 20px;
        border-radius: 6px;
        box-shadow: 0 4px 12px var(--shadow);
        z-index: 10001;
        font-size: 14px;
    `;
    
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}


// ============================================
// EVENT LISTENERS
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    
    const chartForm = document.getElementById('chartForm');
    if (chartForm) {
        chartForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const permanentFilter = chartForm.dataset.permanentfilter;

            const currentParams = new URLSearchParams(window.location.search);

            const catKeys = [];
            for (const key of currentParams.keys()) {
              if (key.startsWith('cat_cat')) {
                catKeys.push(key);
              }
            }
            ['visible_columns', 'page_size', 'page'].forEach(k => currentParams.delete(k));
            catKeys.forEach(k => currentParams.delete(k));

            for (let [key, value] of formData.entries()) {
                currentParams.append(key, value);
            }

            currentParams.append('permanentfilter', permanentFilter);

            const url = `/${currentAppName}/charts/?` + currentParams.toString();
            window.open(url, '_blank');

            closeChartModal();
        });
    }
    

    const modal = document.getElementById('chartModal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === this) closeChartModal();
        });
        
        const modalDialog = modal.querySelector('.modalchart-dialog');
        if (modalDialog) {
            modalDialog.addEventListener('click', function(e) {
                e.stopPropagation();
            });
        }
    }
    
    // Close dropdown when clicking outside
    document.addEventListener('click', function(e) {
        const dropdown = document.getElementById('savedChartDropdown');
        const button = document.getElementById('savedChartButton');
        
        if (dropdown && button && 
            !dropdown.contains(e.target) && 
            !button.contains(e.target)) {
            closeSavedChartDropdown();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const dropdown = document.getElementById('savedChartDropdown');
            if (dropdown && dropdown.classList.contains('show')) {
                closeSavedChartDropdown();
            } else if (modal && modal.classList.contains('show')) {
                closeChartModal();
            }
        }
    });
});