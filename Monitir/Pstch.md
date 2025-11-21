# 🔧 MODIFICATIONS À APPORTER À cluster_status.html

## 1. Ajouter ce CSS dans la section <style> (après .check-badge.error)

```css
/* Détails des checks - Section extensible */
.checks-details {
    margin-top: 15px;
    padding-top: 15px;
    border-top: 2px solid #e9ecef;
}

.checks-details-header {
    cursor: pointer;
    padding: 10px;
    background: #f8f9fa;
    border-radius: 6px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 500;
    user-select: none;
}

.checks-details-header:hover {
    background: #e9ecef;
}

.expand-icon {
    transition: transform 0.3s;
    font-size: 12px;
}

.expand-icon.expanded {
    transform: rotate(180deg);
}

.checks-table-container {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.3s ease-out;
}

.checks-table-container.expanded {
    max-height: 1000px;
    padding-top: 10px;
}

.checks-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}

.checks-table th {
    background: #f8f9fa;
    padding: 8px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #dee2e6;
}

.checks-table td {
    padding: 8px;
    border-bottom: 1px solid #e9ecef;
}

.checks-table tr:last-child td {
    border-bottom: none;
}

.check-status-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
}

.check-status-badge.ok { background: #d4edda; color: #155724; }
.check-status-badge.warning { background: #fff3cd; color: #856404; }
.check-status-badge.error { background: #f8d7da; color: #721c24; }
```

## 2. Remplacer la section des nodes dans displayStatus() (ligne ~200)

Trouve cette partie dans la fonction displayStatus() :

```javascript
// Nodes
if (data.nodes && data.nodes.length > 0) {
    html += '<div class="nodes-grid">';
    
    data.nodes.forEach(node => {
```

Et remplace TOUT le bloc jusqu’à `html += '</div>';` par :

```javascript
// Nodes
if (data.nodes && data.nodes.length > 0) {
    html += '<div class="nodes-grid">';
    
    data.nodes.forEach((node, index) => {
        const nodeStatus = node.status || 'Unknown';
        const statusClass = nodeStatus.toLowerCase();
        const checks = node.checks_summary || {};
        const detailsId = `checks-${index}`;
        
        html += `
            <div class="node-card">
                <div class="node-header ${statusClass}">
                    <div class="node-name">${node.node_name}</div>
                    <span class="node-status ${statusClass}">${nodeStatus}</span>
                    ${node.is_stale ? ' <span style="color: #dc3545;">⚠️ Stale</span>' : ''}
                </div>
                <div class="node-info">
                    <div class="info-row">
                        <span class="info-label">Hostname</span>
                        <span class="info-value">${node.hostname || 'N/A'}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">IP Address</span>
                        <span class="info-value">${node.ip_address || 'N/A'}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Version</span>
                        <span class="info-value">${node.version || 'N/A'}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Dernière mise à jour</span>
                        <span class="info-value">${formatTimestamp(node.last_updated)}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Ancienneté</span>
                        <span class="info-value">${formatStaleness(node.staleness_seconds)}</span>
                    </div>
                    <div class="checks-summary">
                        ${checks.ok > 0 ? `<span class="check-badge ok">✓ ${checks.ok} OK</span>` : ''}
                        ${checks.warning > 0 ? `<span class="check-badge warning">⚠ ${checks.warning} Warning</span>` : ''}
                        ${checks.error > 0 ? `<span class="check-badge error">✗ ${checks.error} Error</span>` : ''}
                    </div>
                    
                    ${node.checks_data && node.checks_data.checks ? `
                        <div class="checks-details">
                            <div class="checks-details-header" onclick="toggleChecks('${detailsId}')">
                                <span>📋 Détails des checks (${node.checks_data.checks.length})</span>
                                <span class="expand-icon" id="icon-${detailsId}">▼</span>
                            </div>
                            <div class="checks-table-container" id="${detailsId}">
                                <table class="checks-table">
                                    <thead>
                                        <tr>
                                            <th>Check</th>
                                            <th>Status</th>
                                            <th>Détails</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${node.checks_data.checks.map(check => `
                                            <tr>
                                                <td><strong>${check.Name || 'Unknown'}</strong></td>
                                                <td>
                                                    <span class="check-status-badge ${(check.Status || 'unknown').toLowerCase()}">
                                                        ${check.Status || 'Unknown'}
                                                    </span>
                                                </td>
                                                <td>${check.Details || check.Error || '-'}</td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    });
    
    html += '</div>';
}
```

## 3. Ajouter cette fonction JavaScript (avant le dernier </script>)

```javascript
function toggleChecks(id) {
    const container = document.getElementById(id);
    const icon = document.getElementById('icon-' + id);
    
    if (container.classList.contains('expanded')) {
        container.classList.remove('expanded');
        icon.classList.remove('expanded');
    } else {
        container.classList.add('expanded');
        icon.classList.add('expanded');
    }
}
```

## 4. Modifier l’appel à loadStatus() pour inclure les détails

Trouve cette ligne (vers ligne ~290) :

```javascript
fetch('/api/status')
```

Et remplace par :

```javascript
fetch('/api/status?details=true')
```

C’est tout ! Maintenant quand tu cliques sur “📋 Détails des checks”, ça déploie un tableau avec tous les checks.
