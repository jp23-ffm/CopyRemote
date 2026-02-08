/**
 * Column Lazy Loader for Inventory Application
 *
 * This module handles dynamic loading of column data without page reload.
 * Columns are loaded on-demand when the user enables them in the sidebar.
 */

(function() {
    'use strict';

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    const CONFIG = {
        // API endpoints
        apiColumnData: '/inventory/api/column-data/',
        apiListboxValues: '/inventory/api/listbox-values/',

        // Cache settings
        cacheEnabled: true,
        cacheDuration: 5 * 60 * 1000, // 5 minutes

        // UI settings
        loadingIndicatorDelay: 100, // ms before showing loading indicator
        batchLoadDelay: 50, // ms delay between batch requests
    };

    // ========================================================================
    // STATE MANAGEMENT
    // ========================================================================

    const state = {
        // Currently loaded columns (data available in DOM)
        loadedColumns: new Set(),

        // Columns currently being loaded
        loadingColumns: new Set(),

        // Column data cache: { columnName: { hostname: value, ... } }
        columnCache: {},

        // Cache timestamps: { columnName: timestamp }
        cacheTimestamps: {},

        // Current page data
        currentPage: 1,
        pageSize: 50,
        currentFilters: {},
        permanentFilter: 'All Servers',
        viewMode: 'grouped', // 'flat' or 'grouped'

        // Hostnames on current page
        currentHostnames: [],
        
        // Track if filter.js has already set up listeners
        filterJsInitialized: false,
    };

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    function init() {
        // Get initial state from page
        initializeState();

        // Setup lazy load listeners (without removing filter.js listeners)
        setupLazyLoadListeners();

        // Mark initially visible columns as loaded
        markInitialColumnsLoaded();

        console.log('[ColumnLazyLoader] Initialized', {
            loadedColumns: Array.from(state.loadedColumns),
            hostnames: state.currentHostnames.length
        });
    }

    function initializeState() {
        // Get current page info from URL
        const urlParams = new URLSearchParams(window.location.search);
        state.currentPage = parseInt(urlParams.get('page')) || 1;
        state.pageSize = parseInt(urlParams.get('page_size')) || 50;
        state.viewMode = urlParams.get('view') === 'flat' ? 'flat' : 'grouped';

        // Get permanent filter from button text
        const permFilterBtn = document.getElementById('permanentFilterButton');
        if (permFilterBtn) {
            state.permanentFilter = permFilterBtn.textContent.trim().replace(/\s*▼\s*$/, '').trim();
        }

        // Extract filters from URL
        state.currentFilters = Object.fromEntries(urlParams.entries());
        delete state.currentFilters.page;
        delete state.currentFilters.page_size;
        delete state.currentFilters.visible_columns;
        delete state.currentFilters.view;

        // Get hostnames from current page
        const rows = document.querySelectorAll('#serversTable tbody tr.primary-row');
        state.currentHostnames = Array.from(rows).map(row => row.getAttribute('data-hostname')).filter(Boolean);
    }

    function markInitialColumnsLoaded() {
        // Get visible columns from checkboxes
        const checkedBoxes = document.querySelectorAll('.column-checkbox:checked');
        checkedBoxes.forEach(checkbox => {
            const columnName = checkbox.getAttribute('data-column');
            if (columnName) {
                state.loadedColumns.add(columnName);
            }
        });

        // Also mark SERVER_ID as always loaded (it's the key column)
        state.loadedColumns.add('SERVER_ID');
    }

    // ========================================================================
    // EVENT LISTENERS (FIXED - ADD INSTEAD OF REPLACE)
    // ========================================================================

    function setupLazyLoadListeners() {
        // Add lazy load logic to existing column checkboxes WITHOUT removing filter.js listeners
        const checkboxes = document.querySelectorAll('.column-checkbox');

        checkboxes.forEach(checkbox => {
            // Add listener (don't clone/replace - that removes filter.js listeners!)
            checkbox.addEventListener('change', handleColumnCheckboxChange);
        });

        // Add category checkbox listeners
        const categoryCheckboxes = document.querySelectorAll('.category-checkbox');
        categoryCheckboxes.forEach(checkbox => {
            checkbox.addEventListener('change', handleCategoryCheckboxChange);
        });
    }

    function handleColumnCheckboxChange(e) {
        const columnName = this.getAttribute('data-column');

        if (this.checked) {
            // Column enabled - load data if not already loaded
            showColumn(columnName);

            if (!state.loadedColumns.has(columnName) && !state.loadingColumns.has(columnName)) {
                loadColumnData([columnName]);
            }
        } else {
            // Column disabled - just hide it (keep data in cache)
            hideColumn(columnName);
        }

        // Update URL without reload
        updateVisibleColumnsInUrl();
    }

    function handleCategoryCheckboxChange(e) {
        const category = this.getAttribute('data-category');
        const categoryContent = document.getElementById(category);

        if (!categoryContent) return;

        const columnCheckboxes = categoryContent.querySelectorAll('.column-checkbox:not(:disabled)');
        const columnsToLoad = [];

        columnCheckboxes.forEach(colCheckbox => {
            const columnName = colCheckbox.getAttribute('data-column');
            
            // Don't manually set checked - let filter.js handle it
            // colCheckbox.checked = this.checked;

            if (this.checked) {
                showColumn(columnName);
                if (!state.loadedColumns.has(columnName) && !state.loadingColumns.has(columnName)) {
                    columnsToLoad.push(columnName);
                }
            } else {
                hideColumn(columnName);
            }
        });

        // Batch load all columns for this category
        if (columnsToLoad.length > 0) {
            loadColumnData(columnsToLoad);
        }

        updateVisibleColumnsInUrl();
    }

    // ========================================================================
    // COLUMN VISIBILITY
    // ========================================================================

    function showColumn(columnName) {
        // Show header
        const header = document.querySelector(`#serversTable th.${columnName}`);
        if (header) {
            header.style.display = '';
        }

        // Show all cells for this column
        const cells = document.querySelectorAll(`#serversTable td.${columnName}`);
        cells.forEach(cell => {
            cell.style.display = '';
        });
    }

    function hideColumn(columnName) {
        // Hide header
        const header = document.querySelector(`#serversTable th.${columnName}`);
        if (header) {
            header.style.display = 'none';
        }

        // Hide all cells for this column
        const cells = document.querySelectorAll(`#serversTable td.${columnName}`);
        cells.forEach(cell => {
            cell.style.display = 'none';
        });
    }

    // ========================================================================
    // DATA LOADING
    // ========================================================================

    async function loadColumnData(columns) {
        if (!columns || columns.length === 0) return;

        // Filter out columns already loaded or loading
        const columnsToLoad = columns.filter(col => 
            !state.loadedColumns.has(col) && !state.loadingColumns.has(col)
        );

        if (columnsToLoad.length === 0) {
            console.log('[ColumnLazyLoader] All requested columns already loaded');
            return;
        }

        // Check cache first
        const cachedColumns = columnsToLoad.filter(col => isCacheValid(col));
        const uncachedColumns = columnsToLoad.filter(col => !isCacheValid(col));

        // Apply cached data immediately
        cachedColumns.forEach(col => {
            applyColumnDataToTable(col, state.columnCache[col]);
            showColumn(col);
            state.loadedColumns.add(col);
        });

        if (uncachedColumns.length === 0) {
            console.log('[ColumnLazyLoader] All columns loaded from cache');
            return;
        }

        // Mark as loading
        uncachedColumns.forEach(col => state.loadingColumns.add(col));

        // Show loading indicators
        showLoadingIndicators(uncachedColumns);

        try {
            // Build request params
            const params = new URLSearchParams();
            params.append('hostnames', state.currentHostnames.join(','));
            params.append('columns', uncachedColumns.join(','));
            params.append('page', state.currentPage);
            params.append('page_size', state.pageSize);
            params.append('view_mode', state.viewMode);

            // Add current filters
            Object.entries(state.currentFilters).forEach(([key, value]) => {
                params.append(key, value);
            });

            const response = await fetch(`${CONFIG.apiColumnData}?${params.toString()}`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            if (result.error) {
                throw new Error(result.error);
            }

            // Process and cache the data
            uncachedColumns.forEach(col => {
                const columnData = extractColumnData(result.data, col);

                // Cache the data
                state.columnCache[col] = columnData;
                state.cacheTimestamps[col] = Date.now();

                // Apply to table
                applyColumnDataToTable(col, columnData);

                // Mark as loaded
                state.loadedColumns.add(col);
                state.loadingColumns.delete(col);
            });

            console.log('[ColumnLazyLoader] Loaded columns:', uncachedColumns);

        } catch (error) {
            console.error('[ColumnLazyLoader] Error loading columns:', error);

            // Mark as not loading on error
            uncachedColumns.forEach(col => state.loadingColumns.delete(col));

            // Show error in cells
            showErrorInColumns(uncachedColumns, error.message);
        } finally {
            hideLoadingIndicators(uncachedColumns);
        }
    }

    function extractColumnData(responseData, columnName) {
        const columnData = {};

        for (const [hostname, serverData] of Object.entries(responseData)) {
            if (state.viewMode === 'flat') {
                // Flat mode: single value per hostname
                if (serverData.instances && serverData.instances.length > 0) {
                    columnData[hostname] = serverData.instances[0][columnName] || '';
                }
            } else {
                // Grouped mode: check constant/variable fields
                if (serverData.constant_fields && columnName in serverData.constant_fields) {
                    columnData[hostname] = {
                        type: 'constant',
                        value: serverData.constant_fields[columnName]
                    };
                } else if (serverData.variable_fields && columnName in serverData.variable_fields) {
                    columnData[hostname] = {
                        type: 'variable',
                        value: serverData.variable_fields[columnName]
                    };
                } else if (serverData.instances && serverData.instances.length > 0) {
                    // Fall back to first instance
                    columnData[hostname] = {
                        type: 'constant',
                        value: serverData.instances[0][columnName] || ''
                    };
                }

                // Also store instance data for detail rows
                if (serverData.instances) {
                    columnData[hostname + '_instances'] = serverData.instances.map(inst => inst[columnName] || '');
                }
            }
        }

        return columnData;
    }

    function applyColumnDataToTable(columnName, columnData) {
        // Get all rows
        const rows = document.querySelectorAll('#serversTable tbody tr');

        rows.forEach(row => {
            const hostname = row.getAttribute('data-hostname');
            if (!hostname) return;

            const cell = row.querySelector(`td.${columnName}`);
            if (!cell) return;

            const isPrimaryRow = row.classList.contains('primary-row');
            const isDetailRow = row.classList.contains('detail-row');

            if (state.viewMode === 'flat' || isPrimaryRow) {
                // Primary row or flat mode
                const data = columnData[hostname];

                if (!data) {
                    cell.innerHTML = '-';
                    return;
                }

                if (typeof data === 'string') {
                    // Flat mode: simple value
                    cell.innerHTML = data || '-';
                } else if (data.type === 'constant') {
                    cell.innerHTML = data.value || '-';
                } else if (data.type === 'variable') {
                    const preview = data.value?.preview || data.value || '';
                    cell.innerHTML = `<span class="variable-field">${preview}</span>`;
                }
            } else if (isDetailRow) {
                // Detail row - get instance data
                const instanceData = columnData[hostname + '_instances'];
                if (instanceData) {
                    // Find instance number from row
                    const instanceBadge = row.querySelector('.instance-badge');
                    if (instanceBadge) {
                        const badgeText = instanceBadge.textContent.trim();
                        const match = badgeText.match(/^(\d+)\//);
                        if (match) {
                            const instanceIndex = parseInt(match[1]) - 1;
                            if (instanceData[instanceIndex] !== undefined) {
                                cell.innerHTML = instanceData[instanceIndex] || '<span class="empty-field">--</span>';
                            }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // CACHE MANAGEMENT
    // ========================================================================

    function isCacheValid(columnName) {
        if (!CONFIG.cacheEnabled) return false;
        if (!state.columnCache[columnName]) return false;
        if (!state.cacheTimestamps[columnName]) return false;

        const age = Date.now() - state.cacheTimestamps[columnName];
        return age < CONFIG.cacheDuration;
    }

    function clearCache(columnName = null) {
        if (columnName) {
            delete state.columnCache[columnName];
            delete state.cacheTimestamps[columnName];
        } else {
            state.columnCache = {};
            state.cacheTimestamps = {};
        }
    }

    // ========================================================================
    // UI HELPERS
    // ========================================================================

    function showLoadingIndicators(columns) {
        columns.forEach(col => {
            const cells = document.querySelectorAll(`#serversTable td.${col}`);
            cells.forEach(cell => {
                if (!cell.querySelector('.loading-spinner')) {
                    cell.innerHTML = '<span class="loading-spinner">...</span>';
                }
            });
        });
    }

    function hideLoadingIndicators(columns) {
        // Loading indicators are replaced by actual data in applyColumnDataToTable
    }

    function showErrorInColumns(columns, errorMessage) {
        columns.forEach(col => {
            const cells = document.querySelectorAll(`#serversTable td.${col}`);
            cells.forEach(cell => {
                cell.innerHTML = '<span class="error-cell" title="' + errorMessage + '">!</span>';
            });
        });
    }

    function updateVisibleColumnsInUrl() {
        const visibleColumns = Array.from(document.querySelectorAll('.column-checkbox:checked'))
            .map(cb => cb.getAttribute('data-column'))
            .filter(Boolean);

        const url = new URL(window.location.href);
        url.searchParams.set('visible_columns', visibleColumns.join(','));

        // Update URL without reload
        window.history.replaceState({}, '', url.toString());
    }

    // ========================================================================
    // PUBLIC API
    // ========================================================================

    window.ColumnLazyLoader = {
        init,
        loadColumnData,
        showColumn,
        hideColumn,
        clearCache,
        getState: () => ({ ...state }),
    };

    // ========================================================================
    // AUTO-INITIALIZE
    // ========================================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
