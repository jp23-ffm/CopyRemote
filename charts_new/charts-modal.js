// Ajouter dans le HTML du modal (après les sélecteurs de charts)

div.innerHTML = `
    <!-- Tes sélecteurs existants -->
    
    <!-- NOUVEAU : Section Saved Queries -->
    <div class="saved-queries-section" style="margin-top: 20px; padding-top: 20px; border-top: 2px solid var(--border-color);">
        <h6 style="margin-bottom: 10px; color: var(--text-primary);">💾 Saved Views</h6>
        
        <select id="savedQuerySelect" style="width: 100%; padding: 10px; margin-bottom: 10px;">
            <option value="">-- Load a saved view --</option>
        </select>
        
        <div style="display: flex; gap: 10px;">
            <button type="button" class="btn btn-secondary" onclick="loadSavedQuery()" style="flex: 1;">
                📂 Load
            </button>
            <button type="button" class="btn btn-secondary" onclick="openSaveQueryDialog()" style="flex: 1;">
                💾 Save Current
            </button>
        </div>
    </div>
`;

// Charger les saved queries au chargement
async function loadSavedQueriesList() {
    try {
        const response = await fetch('/api/saved-queries/');
        const data = await response.json();
        
        if (data.success) {
            const select = document.getElementById('savedQuerySelect');
            select.innerHTML = '<option value="">-- Load a saved view --</option>';
            
            data.queries.forEach(query => {
                const option = document.createElement('option');
                option.value = query.id;
                option.textContent = `${query.name} (${query.chart_count} charts, ${query.filters_count} filters)`;
                option.dataset.queryString = query.query_string;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Error loading saved queries:', error);
    }
}

function loadSavedQuery() {
    const select = document.getElementById('savedQuerySelect');
    const selectedOption = select.options[select.selectedIndex];
    
    if (!selectedOption.value) {
        alert('Please select a saved view');
        return;
    }
    
    const queryString = selectedOption.dataset.queryString;
    
    // Ouvrir la page charts avec la query sauvegardée
    window.open(`/charts/?${queryString}`, '_blank');
    
    // Incrémenter le compteur d'utilisation
    fetch(`/api/saved-queries/${selectedOption.value}/load/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken')
        }
    });
    
    closeChartModal();
}

function openSaveQueryDialog() {
    const name = prompt('Enter a name for this view:');
    if (!name) return;
    
    const description = prompt('Enter a description (optional):');
    
    // Construire la query string actuelle
    const params = new URLSearchParams(window.location.search);
    
    // Ajouter les champs du formulaire
    const formData = new FormData(document.getElementById('chartForm'));
    for (let [key, value] of formData.entries()) {
        params.append(key, value);
    }
    
    const queryString = params.toString();
    
    // Sauvegarder
    fetch('/api/saved-queries/save/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            name: name,
            description: description || '',
            queryString: queryString
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(`View "${name}" saved successfully!`);
            loadSavedQueriesList(); // Recharger la liste
        } else {
            alert('Error: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error saving query:', error);
        alert('Error saving view');
    });
}

// Charger les saved queries quand le modal s'ouvre
function openChartModal() {
    // ... ton code existant ...
    
    // Charger les saved queries
    loadSavedQueriesList();
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