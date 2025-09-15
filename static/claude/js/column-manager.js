// static/myapp/js/column-manager.js
class ColumnManager {
    constructor(configPath = '/static/claude/js/column-config.json') {
        this.configPath = configPath;
        this.config = null;
        this.userPrefs = this.loadUserPreferences();
        this.styleSheet = null;
        this.isFlatView = false;
        
        this.init();
    }
    
    async init() {
        try {
            // Detect current view mode
            this.detectViewMode();
            
            await this.loadConfig();
            this.createDynamicStyleSheet();
            this.applyColumnStyles();
            this.setupResponsiveHandling();
            this.setupColumnToggle();
            
            console.log('[ColumnManager] Initialized successfully - Mode:', this.isFlatView ? 'Flat' : 'Grouped');
        } catch (error) {
            console.error('[ColumnManager] Initialization error:', error);
        }
    }
    
    detectViewMode() {
        // Detect if we're in flat view by checking for +/- and Info headers
        const expandHeader = document.querySelector('th.col-expand');
        const infoHeader = document.querySelector('th.col-info');
        this.isFlatView = !expandHeader && !infoHeader;
        
        console.log('[ColumnManager] Mode detected:', this.isFlatView ? 'Flat view' : 'Grouped view');
    }
    
    async loadConfig() {
        try {
            const response = await fetch(this.configPath);
            this.config = await response.json();
            console.log('[ColumnManager] Configuration loaded:', this.config);
        } catch (error) {
            console.error('[ColumnManager] Cannot load config:', error);
            this.config = this.getDefaultConfig();
        }
    }
    
    createDynamicStyleSheet() {
        // Create dynamic stylesheet
        this.styleSheet = document.createElement('style');
        this.styleSheet.id = 'column-manager-styles';
        document.head.appendChild(this.styleSheet);
    }
    
    applyColumnStyles() {
        if (!this.config || !this.styleSheet) return;
        
        let css = '';
        const columns = this.config.columns;
        
        // Base CSS to ensure consistency
        css += `
        /* Base styles for all columns */
        th {
            background: #f8f9fa;
            position: sticky;
            top: 0;
            z-index: 10;
        }
        
        /* Special sticky columns */
        th.col-expand, th.col-info, th.col-hostname {
            background: #f8f9fa !important;
            z-index: 11 !important;
        }
        
        td.col-expand, td.col-info, td.col-hostname {
            z-index: 5 !important;
        }
        
        /* Ensure opacity for sticky columns */
        tr.primary-row td.col-expand, tr.primary-row td.col-info, tr.primary-row td.col-hostname,
        tr.flat-row td.col-expand, tr.flat-row td.col-info, tr.flat-row td.col-hostname {
            background: white !important;
        }
        
        tr.detail-row td.col-expand, tr.detail-row td.col-info, tr.detail-row td.col-hostname {
            background: #f8f9fa !important;
        }
        `;
        
        // Generate CSS for each column
        Object.entries(columns).forEach(([className, config]) => {
            // In flat view, ignore expand and info columns
            if (this.isFlatView && (className === 'col-expand' || className === 'col-info')) {
                return;
            }
            
            const finalConfig = this.mergeWithUserPrefs(className, config);
            css += this.generateColumnCSS(className, finalConfig);
        });
        
        // In flat view, adjust hostname sticky position
        if (this.isFlatView) {
            css += `th.col-hostname, td.col-hostname {`;
            css += ' position: sticky;';
            css += ' left: 0px;';  // First column in flat view
            css += ' z-index: 5;';
            css += ' background: inherit;';
            css += '}\n';
            
            css += `th.col-hostname {`;
            css += ' background: #f8f9fa !important;';
            css += ' z-index: 11;';
            css += '}\n';
            
            css += `tr.flat-row td.col-hostname {`;
            css += ' background: white !important;';
            css += '}\n';
        }
        
        // Add responsive breakpoints
        css += this.generateResponsiveCSS();
        
        // Apply CSS
        this.styleSheet.textContent = css;
        
        console.log('[ColumnManager] Styles applied for mode:', this.isFlatView ? 'Flat' : 'Grouped');
    }
    
    mergeWithUserPrefs(className, config) {
        const userPref = this.userPrefs[className];
        return userPref ? { ...config, ...userPref } : config;
    }
    
    generateColumnCSS(className, config) {
        let css = `.${className} {`;
        
        // Width
        if (config.width) {
            if (config.width === 'auto') {
                css += ' width: auto;';
            } else {
                css += ` width: ${config.width};`;
            }
        }
        
        // Min/max width
        if (config.minWidth) {
            css += ` min-width: ${config.minWidth};`;
        }
        if (config.maxWidth && config.maxWidth !== 'none') {
            css += ` max-width: ${config.maxWidth};`;
        }
        
        // Sticky
        if (config.sticky) {
            css += ' position: sticky;';
            css += ' z-index: 5;';
            
            // Use stickyLeft if defined, otherwise default values
            if (config.stickyLeft) {
                css += ` left: ${config.stickyLeft};`;
            } else {
                // Fallback for compatibility
                if (className === 'col-expand') {
                    css += ' left: 0;';
                } else if (className === 'col-info') {
                    css += ' left: 50px;';
                } else if (className === 'col-hostname') {
                    css += ' left: 130px;';
                }
            }
        }
        
        // Visibility
        if (!config.visible) {
            css += ' display: none;';
        }
        
        // Resizable
        if (!config.resizable) {
            css += ' resize: none;';
        }
        
        // Overflow
        css += ' overflow: hidden;';
        css += ' text-overflow: ellipsis;';
        css += ' white-space: nowrap;';
        
        css += '}\n';
        
        // Specific background for sticky headers
        if (config.sticky) {
            css += `th.${className} {`;
            css += ' background: #f8f9fa !important;';  // !important to force gray
            css += ' z-index: 11;';
            css += '}\n';
            
            // Background for normal row cells - OPAQUE
            css += `tr.primary-row td.${className}, tr.flat-row td.${className} {`;
            css += ' background: white !important;';  // !important to be opaque
            css += ' z-index: 5;';
            css += '}\n';
            
            // Background for detail row cells - OPAQUE
            css += `tr.detail-row td.${className} {`;
            css += ' background: #f8f9fa !important;';  // !important to be opaque
            css += ' z-index: 5;';
            css += '}\n';
        }
        
        // Hover effect to see full content (except sticky columns)
        if (!config.sticky) {
            css += `.${className}:hover {`;
            css += ' overflow: visible;';
            css += ' white-space: normal;';
            css += ' background: #fff3cd;';
            css += ' position: relative;';
            css += ' z-index: 10;';
            css += '}\n';
        }
        
        return css;
    }
    
    generateResponsiveCSS() {
        let css = '';
        const breakpoints = this.config.breakpoints;
        const columns = this.config.columns;
        
        // Mobile
        css += `@media (max-width: ${breakpoints.mobile}) {\n`;
        Object.entries(columns).forEach(([className, config]) => {
            if (config.hideOnMobile) {
                css += `.${className} { display: none !important; }\n`;
            }
        });
        css += '}\n';
        
        // Tablet
        css += `@media (max-width: ${breakpoints.tablet}) {\n`;
        Object.entries(columns).forEach(([className, config]) => {
            if (config.hideOnTablet) {
                css += `.${className} { display: none !important; }\n`;
            }
        });
        css += '}\n';
        
        return css;
    }
    
    setupResponsiveHandling() {
        // Handle screen size changes
        window.addEventListener('resize', this.debounce(() => {
            this.applyColumnStyles();
        }, 100));
        
        // Handle view mode changes (via toggle buttons)
        document.addEventListener('click', (event) => {
            if (event.target.classList.contains('view-btn')) {
                // Small delay to let DOM update
                setTimeout(() => {
                    this.detectViewMode();
                    this.applyColumnStyles();
                }, 100);
            }
        });
    }
    
    setupColumnToggle() {
        if (!this.config.settings.enableColumnToggle) return;
        
        // Create toggle controls
        this.createColumnToggleControls();
    }
    
    createColumnToggleControls() {
        const panelContent = document.querySelector('.panel-content');
        if (!panelContent) return;
        
        // Clear existing content
        panelContent.innerHTML = '';
        
        // Create controls
        const controlsHTML = `
            <div class="column-controls">
                <div class="control-group">
                    <button class="btn-toggle-all" onclick="columnManager.toggleAllColumns()">
                        All columns
                    </button>
                </div>
                <div class="column-list"></div>
            </div>
        `;
        
        panelContent.innerHTML = controlsHTML;
        const columnList = panelContent.querySelector('.column-list');
        
        // Create checkbox for each column
        Object.entries(this.config.columns).forEach(([className, config]) => {
            // Don't allow hiding essential columns
            if (config.priority > 1) {
                const checkboxWrapper = document.createElement('label');
                checkboxWrapper.className = 'column-checkbox';
                checkboxWrapper.innerHTML = `
                    <input type="checkbox" ${config.visible ? 'checked' : ''} 
                           onchange="columnManager.toggleColumn('${className}', this.checked)">
                    <span class="checkbox-label">${this.getColumnDisplayName(className)}</span>
                `;
                columnList.appendChild(checkboxWrapper);
            }
        });
    }
    
    getColumnDisplayName(className) {
        const displayNames = {
    'col-hostname': 'Hostname',
    'col-ip_address': 'IP Address',
    'col-dns_primary': 'Primary DNS',
    'col-os': 'OS',
    'col-os_version': 'OS Version',
    'col-ram': 'RAM',
    'col-cpu': 'CPU',
    'col-cpu_cores': 'CPU Cores',
    'col-storage_type': 'Storage Type',
    'col-storage_size': 'Storage Size',
    'col-datacenter': 'Datacenter',
    'col-rack': 'Rack',
    'col-availability_zone': 'Availability Zone',
    'col-network_vlan': 'VLAN',
    'col-network_speed': 'Network Speed',
    'col-application': 'Application',
    'col-service_level': 'Service Level',
    'col-db_instance': 'DB Instance',
    'col-owner': 'Owner',
    'col-business_unit': 'Business Unit',
    'col-cost_center': 'Cost Center',
    'col-project_code': 'Project Code',
    'col-support_email': 'Support Email',
    'col-virtualization': 'Virtualization',
    'col-security_zone': 'Security Zone',
    'col-compliance_level': 'Compliance',
    'col-antivirus': 'Antivirus',
    'col-patch_group': 'Patch Group',
    'col-monitoring_tool': 'Monitoring',
    'col-backup_policy': 'Backup Policy',
    'col-maintenance_window': 'Maintenance Window',
    'col-power_state': 'Power State',
    'col-health_status': 'Health Status',
    'col-deployment_status': 'Deployment Status',
    'col-cpu_utilization': 'CPU %',
    'col-memory_utilization': 'Memory %',
    'col-disk_utilization': 'Disk %',
    'col-serial_number': 'Serial Number',
    'col-asset_tag': 'Asset Tag',
    'col-install_date': 'Install Date',
    'col-last_boot_time': 'Last Boot',
    'col-warranty_expiry': 'Warranty Expiry',
    'col-annotations': 'Annotations'
    };
        return displayNames[className] || className.replace('col-', '').replace('_', ' ');
    }
    
    toggleColumn(className, visible) {
        // Update config
        if (this.config.columns[className]) {
            this.config.columns[className].visible = visible;
        }
        
        // Save user preferences
        this.userPrefs[className] = { visible };
        this.saveUserPreferences();
        
        // Reapply styles
        this.applyColumnStyles();
        
        console.log(`[ColumnManager] Column ${className} ${visible ? 'shown' : 'hidden'}`);
    }
    
    toggleAllColumns() {
        const allVisible = Object.values(this.config.columns)
            .filter(config => config.priority > 1)
            .every(config => config.visible);
        
        Object.entries(this.config.columns).forEach(([className, config]) => {
            if (config.priority > 1) {
                this.toggleColumn(className, !allVisible);
            }
        });
        
        // Update checkboxes
        const checkboxes = document.querySelectorAll('.column-checkbox input');
        checkboxes.forEach(cb => cb.checked = !allVisible);
    }
    
    loadUserPreferences() {
        if (!this.config?.settings?.saveUserPreferences) return {};
        
        try {
            const saved = localStorage.getItem('columnPreferences');
            return saved ? JSON.parse(saved) : {};
        } catch (error) {
            console.warn('[ColumnManager] Cannot load preferences:', error);
            return {};
        }
    }
    
    saveUserPreferences() {
        if (!this.config?.settings?.saveUserPreferences) return;
        
        try {
            localStorage.setItem('columnPreferences', JSON.stringify(this.userPrefs));
        } catch (error) {
            console.warn('[ColumnManager] Cannot save preferences:', error);
        }
    }
    
    getDefaultConfig() {
        return {
            columns: {
                'col-hostname': { width: '200px', minWidth: '150px', visible: true },
                'col-os': { width: '120px', visible: true },
                'col-application': { width: 'auto', minWidth: '130px', visible: true }
            },
            breakpoints: { mobile: '768px', tablet: '1200px' },
            settings: { enableColumnToggle: true, saveUserPreferences: true }
        };
    }
    
    // Utility function
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
}

// Global initialization
let columnManager;
document.addEventListener('DOMContentLoaded', () => {
    columnManager = new ColumnManager();
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ColumnManager;
}