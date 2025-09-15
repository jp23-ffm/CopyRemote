// static/myapp/js/server_list.js
const ServerState = {
    STORAGE_KEY: 'server_expanded_state',
    
    debugLog(message, data) {
        console.log('[ServerState]', message, data || '');
    },
    
    // Simple getters/setters for sessionStorage
    getExpandedServers() {
        try {
            const stored = sessionStorage.getItem(this.STORAGE_KEY);
            return stored ? JSON.parse(stored) : [];
        } catch (e) {
            this.debugLog('Error getting expanded servers:', e.message);
            return [];
        }
    },
    
    setExpandedServers(list) {
        try {
            sessionStorage.setItem(this.STORAGE_KEY, JSON.stringify(list));
            this.debugLog('Saved expanded servers:', list);
        } catch (e) {
            this.debugLog('Error saving expanded servers:', e.message);
        }
    },
    
    // Add server to expanded list (don't save immediately)
    addExpandedServer(hostnameSlug) {
        const expanded = this.getExpandedServers();
        if (!expanded.includes(hostnameSlug)) {
            expanded.push(hostnameSlug);
            this.setExpandedServers(expanded);
            this.debugLog('Added to expanded:', hostnameSlug);
        }
    },
    
    // Remove server from expanded list
    removeExpandedServer(hostnameSlug) {
        const expanded = this.getExpandedServers();
        const index = expanded.indexOf(hostnameSlug);
        if (index > -1) {
            expanded.splice(index, 1);
            this.setExpandedServers(expanded);
            this.debugLog('Removed from expanded:', hostnameSlug);
        }
    },
    
    // Clear all expanded state
    clearAll() {
        this.setExpandedServers([]);
        this.debugLog('Cleared all expanded state');
    },
    
    // Toggle a specific server
    toggleDetails(hostnameSlug) {
        this.debugLog('Toggle details for:', hostnameSlug);
        
        const primaryRow = document.getElementById('primary-' + hostnameSlug);
        const detailRows = document.querySelectorAll('[id^="detail-' + hostnameSlug + '-"]');
        
        if (!primaryRow || detailRows.length === 0) {
            this.debugLog('Error: elements not found for', hostnameSlug);
            return;
        }
        
        const isCurrentlyExpanded = primaryRow.style.display === 'none';
        
        if (isCurrentlyExpanded) {
            // Collapse
            primaryRow.style.display = 'table-row';
            detailRows.forEach(row => row.style.display = 'none');
            
            // Update button
            const expandBtn = primaryRow.querySelector('.expand-btn') || 
                            document.querySelector(`[id^="detail-${hostnameSlug}-"] .expand-btn`);
            if (expandBtn) {
                expandBtn.textContent = '+';
                expandBtn.classList.remove('expanded');
            }
            
            this.removeExpandedServer(hostnameSlug);
            this.debugLog('Collapsed:', hostnameSlug);
        } else {
            // Expand
            primaryRow.style.display = 'none';
            detailRows.forEach(row => row.style.display = 'table-row');
            
            // Update button
            const expandBtn = detailRows[0]?.querySelector('.expand-btn');
            if (expandBtn) {
                expandBtn.textContent = '−';
                expandBtn.classList.add('expanded');
            }
            
            this.addExpandedServer(hostnameSlug);
            this.debugLog('Expanded:', hostnameSlug);
        }
    },
    
    // Restore expanded state on page load
    restoreExpandedState() {
        const expandedServers = this.getExpandedServers();
        this.debugLog('Restoring state for servers:', expandedServers);
        
        if (expandedServers.length === 0) {
            this.debugLog('No servers to restore');
            return;
        }
        
        let restoredCount = 0;
        
        expandedServers.forEach(hostnameSlug => {
            const primaryRow = document.getElementById('primary-' + hostnameSlug);
            const detailRows = document.querySelectorAll('[id^="detail-' + hostnameSlug + '-"]');
            
            this.debugLog(`Attempting to restore: ${hostnameSlug}`, {
                primaryFound: !!primaryRow,
                detailCount: detailRows.length
            });
            
            if (primaryRow && detailRows.length > 0) {
                // Apply expanded state
                primaryRow.style.display = 'none';
                detailRows.forEach(row => row.style.display = 'table-row');
                
                // Update expand button
                const expandBtn = detailRows[0]?.querySelector('.expand-btn');
                if (expandBtn) {
                    expandBtn.textContent = '−';
                    expandBtn.classList.add('expanded');
                }
                
                restoredCount++;
                this.debugLog('Successfully restored:', hostnameSlug);
            } else {
                this.debugLog('Server not found on this page:', hostnameSlug);
            }
        });
        
        this.debugLog(`Restoration complete: ${restoredCount}/${expandedServers.length} servers restored`);
    },
    
    // No automatic state clearing - let users keep their expanded servers
    checkFilterChanges() {
        const currentUrl = window.location.search;
        const lastUrl = sessionStorage.getItem('last_url');
        
        if (lastUrl && lastUrl !== currentUrl) {
            this.debugLog('URL changed but keeping expanded state');
            this.debugLog('Previous URL:', lastUrl);
            this.debugLog('Current URL:', currentUrl);
        }
        
        sessionStorage.setItem('last_url', currentUrl);
    },
    
    // Initialize the system
    init() {
        this.debugLog('Initializing ServerState...');
        
        // Check for filter changes
        this.checkFilterChanges();
        
        // Restore expanded state
        this.restoreExpandedState();
        
        // Setup double-click handlers
        document.querySelectorAll('.server-row').forEach(row => {
            row.addEventListener('dblclick', () => {
                const hostname = row.dataset.hostname;
                if (hostname) {
                    // Use the actual slug from the row ID
                    const rowId = row.closest('.primary-row')?.id || row.id;
                    const slug = rowId.replace('primary-', '');
                    if (slug && slug !== rowId) { // Make sure we found a valid slug
                        this.toggleDetails(slug);
                    }
                }
            });
        });
        
        this.debugLog('ServerState initialized');
    }
};

// Global function for HTML onclick
function toggleDetails(hostnameSlug) {
    ServerState.toggleDetails(hostnameSlug);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    ServerState.init();
});

// Clear all on Escape
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        ServerState.clearAll();
        // Also collapse visible expanded rows
        document.querySelectorAll('.primary-row[style*="none"]').forEach(row => {
            const slug = row.id.replace('primary-', '');
            ServerState.toggleDetails(slug);
        });
    }
});

// Handle browser navigation
window.addEventListener('popstate', () => {
    setTimeout(() => {
        ServerState.checkFilterChanges();
        ServerState.restoreExpandedState();
    }, 100);
});