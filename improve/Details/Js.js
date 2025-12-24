// Récupérer json_data depuis le template (déjà disponible dans ton HTML)
// const jsonData = {{ json_data|safe }}; // Déjà présent dans ton code

let contextMenuServer = null;
let currentServerData = null;

// Plus besoin de FIELD_GROUPS codé en dur !

document.addEventListener('DOMContentLoaded', function() {
    const contextMenu = document.getElementById('contextMenu');
    
    // Click droit sur les lignes du tableau
    document.addEventListener('contextmenu', function(e) {
        const row = e.target.closest('tr[data-server-id]');
        
        if (row) {
            e.preventDefault();
            contextMenuServer = JSON.parse(row.dataset.serverData);
            
            contextMenu.style.display = 'block';
            contextMenu.style.left = e.pageX + 'px';
            contextMenu.style.top = e.pageY + 'px';
        }
    });
    
    document.addEventListener('click', function() {
        contextMenu.style.display = 'none';
    });
    
    contextMenu.addEventListener('click', function(e) {
        e.stopPropagation();
    });
});

function showServerDetails() {
    if (!contextMenuServer) return;
    
    currentServerData = contextMenuServer;
    
    // Mettre à jour le titre
    document.getElementById('serverDetailsTitle').textContent = 
        `Server Details: ${currentServerData.hostname || currentServerData.SERVER_ID}`;
    
    // Générer le contenu en utilisant json_data
    const content = document.getElementById('serverDetailsContent');
    content.innerHTML = '';
    
    // Organiser les champs par catégorie depuis json_data
    const fieldsByCategory = {};
    
    // Parcourir tous les champs de json_data
    for (const [fieldKey, fieldInfo] of Object.entries(jsonData.fields || {})) {
        const category = fieldInfo.selectionsection; // ex: "cat1", "cat2"
        const categoryName = jsonData[category]; // ex: "Application", "Hardware"
        const displayName = fieldInfo.displayname;
        const inputName = fieldInfo.inputname;
        
        // Récupérer la valeur du serveur
        const value = currentServerData[inputName];
        
        // Skip si pas de valeur
        if (value === null || value === undefined || value === '') continue;
        
        // Grouper par catégorie
        if (!fieldsByCategory[categoryName]) {
            fieldsByCategory[categoryName] = [];
        }
        
        fieldsByCategory[categoryName].push({
            displayName: displayName,
            inputName: inputName,
            value: value
        });
    }
    
    // Créer les sections
    for (const [categoryName, fields] of Object.entries(fieldsByCategory)) {
        if (fields.length === 0) continue;
        
        const section = document.createElement('div');
        section.className = 'detail-section';
        
        const header = document.createElement('h6');
        header.textContent = categoryName;
        section.appendChild(header);
        
        // Ajouter les champs
        fields.forEach(field => {
            const fieldDiv = document.createElement('div');
            fieldDiv.className = 'detail-field';
            fieldDiv.setAttribute('data-field', field.inputName);
            
            const label = document.createElement('div');
            label.className = 'detail-label';
            label.textContent = field.displayName;
            
            const valueDiv = document.createElement('div');
            valueDiv.className = 'detail-value';
            
            // Échapper les valeurs pour éviter les injections
            const escapedValue = String(field.value).replace(/'/g, "\\'");
            
            valueDiv.innerHTML = `
                <span>${field.value}</span>
                <span class="copy-icon" onclick="copyToClipboard('${escapedValue}')">📋</span>
            `;
            
            fieldDiv.appendChild(label);
            fieldDiv.appendChild(valueDiv);
            section.appendChild(fieldDiv);
        });
        
        content.appendChild(section);
    }
    
    // Afficher le modal
    document.getElementById('serverDetailsModal').style.display = 'flex';
    document.getElementById('contextMenu').style.display = 'none';
}

function closeServerDetails() {
    document.getElementById('serverDetailsModal').style.display = 'none';
}

function filterDetails(query) {
    const fields = document.querySelectorAll('.detail-field');
    const lowerQuery = query.toLowerCase();
    
    fields.forEach(field => {
        const text = field.textContent.toLowerCase();
        field.style.display = text.includes(lowerQuery) ? '' : 'none';
    });
    
    // Masquer les sections vides
    document.querySelectorAll('.detail-section').forEach(section => {
        const visibleFields = Array.from(section.querySelectorAll('.detail-field'))
            .filter(f => f.style.display !== 'none');
        section.style.display = visibleFields.length > 0 ? '' : 'none';
    });
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        // Feedback visuel élégant
        const toast = document.createElement('div');
        toast.textContent = '✓ Copied!';
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: var(--success-color, #28a745);
            color: white;
            padding: 12px 20px;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 10001;
            animation: slideIn 0.3s ease;
        `;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2000);
    });
}

function copyHostname() {
    if (contextMenuServer) {
        const hostname = contextMenuServer.hostname || contextMenuServer.SERVER_ID;
        copyToClipboard(hostname);
    }
}

function copyIP() {
    if (contextMenuServer) {
        // Chercher le champ IP dans json_data
        const ipField = Object.values(jsonData.fields || {})
            .find(f => f.inputname.toLowerCase().includes('ip'));
        
        if (ipField) {
            copyToClipboard(contextMenuServer[ipField.inputname]);
        }
    }
}

function openInNewTab() {
    if (contextMenuServer) {
        window.open(`/servers/${contextMenuServer.id}/`, '_blank');
    }
}

function exportServerDetails() {
    if (!currentServerData) return;
    
    // Créer un export structuré avec les display names
    const exportData = {};
    
    for (const [fieldKey, fieldInfo] of Object.entries(jsonData.fields || {})) {
        const inputName = fieldInfo.inputname;
        const displayName = fieldInfo.displayname;
        const value = currentServerData[inputName];
        
        if (value !== null && value !== undefined) {
            exportData[displayName] = value;
        }
    }
    
    const dataStr = JSON.stringify(exportData, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    
    const filename = currentServerData.hostname || currentServerData.SERVER_ID || 'server';
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filename}_${new Date().toISOString().split('T')[0]}.json`;
    link.click();
    
    URL.revokeObjectURL(url);
}

// Animation CSS pour le toast
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
`;
document.head.appendChild(style);

// Fermer avec Escape
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeServerDetails();
    }
});
