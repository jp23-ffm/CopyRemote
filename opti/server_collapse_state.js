Dans la fonction toggleDetails (image précédente, ligne 162), modifier la partie "Expand" :
CHERCHER :
} else {
    // Expand
    primaryRow.style.display = 'none';
    detailRows.forEach(row => row.style.display = 'table-row');

REMPLACER PAR :
} else {
    // Expand
    const needsLoading = detailRows[0]?.dataset.needsLoading === 'true';
    
    if (needsLoading) {
        this.loadServerDetails(hostnameSlug, primaryRow, detailRows);
    } else {
        primaryRow.style.display = 'none';
        detailRows.forEach(row => row.style.display = 'table-row');
    }

AJOUTER cette nouvelle fonction (après removeExpandedServer, vers ligne 92) :
loadServerDetails(hostnameSlug, primaryRow, detailRows) {
    const dataJson = primaryRow.dataset.instancesJson;
    
    if (!dataJson) {
        console.error('No data found for', hostnameSlug);
        return;
    }
    
    try {
        const instances = JSON.parse(dataJson);
        
        detailRows.forEach((row, index) => {
            if (index >= instances.length) return;
            
            const instance = instances[index];
            const cells = row.querySelectorAll('td');
            
            // Colonne 0 : expand (vide)
            // Colonne 1 : info (compteur)
            if (cells[1]) {
                cells[1].innerHTML = `<span class="instance-count">${index + 1}/${instances.length}</span>`;
            }
            
            let cellIndex = 2;
            
            // Tous les constant_fields
            for (const value of Object.values(instance.constant_fields)) {
                if (cells[cellIndex]) {
                    cells[cellIndex].textContent = value || '';
                    cellIndex++;
                }
            }
            
            // Tous les variable_fields
            for (const value of Object.values(instance.variable_fields)) {
                if (cells[cellIndex]) {
                    cells[cellIndex].textContent = value || '';
                    cellIndex++;
                }
            }
            
            row.dataset.needsLoading = 'false';
        });
        
        // Afficher
        primaryRow.style.display = 'none';
        detailRows.forEach(row => row.style.display = 'table-row');
        
    } catch (e) {
        console.error('Error parsing instances JSON:', e);
    }
},
