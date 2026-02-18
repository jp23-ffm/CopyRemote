document.addEventListener('DOMContentLoaded', function () {


    const searchInputs = document.querySelectorAll('.search-input');
    const filterTagsDiv = document.querySelector('#filterTags');
    const columnCheckboxes = document.querySelectorAll('.column-checkbox');
    const saveSearchForm = document.getElementById('saveSearchForm');
    const clearFiltersButton = document.getElementById('clearFiltersButton');
    const tableHeaders = document.querySelectorAll('th.resizable');
    const selectAllCheckbox =  document.getElementById('selectAllColumns');
    const tableContainer = document.querySelector('.table-container');
    const jsonScriptElement = document.getElementById('json-data');
    const jsonData = JSON.parse(jsonScriptElement.textContent);
    
    
    /* --  Search for input and listbox elements in serversTable, and save them in an object -- */
    const listboxes = document.querySelectorAll('#serversTable [id$="-listbox"]');
    const elements = {};
    
    listboxes.forEach(listbox => {
        const baseName = listbox.id.replace('-listbox', '');
        const input = document.querySelector(`#serversTable input[name="${baseName}"]`);
        elements[`${baseName}Listbox`] = listbox;
        elements[`${baseName}Input`] = input;
    });

    let filters = {};
    let selectedColumns = [];
    

    /* --  Functions -- */
    
    function clearFilters() {
    
        const url = new URL(window.location.href);
        const params = new URLSearchParams(url.search);
        
        serversTable=document.getElementById('serversTable');
        inputs = serversTable.getElementsByTagName('input');
		console.log(inputs);

        for (index = 0; index < inputs.length; ++index) {
            params.delete(inputs[index].name);
			console.log(inputs[index].name);
        }
    // Remove all params ending with "_inconsistent"
		const keysToDelete = [];
		for (const key of params.keys()) {
			if (key.endsWith('_inconsistent')) {
				keysToDelete.push(key);
			}
		}
		keysToDelete.forEach(key => params.delete(key));

        params.delete('page');
        params.delete('sort');
        params.delete('order');
        if (tableContainer) {
            const currentScrollLeft = tableContainer.scrollLeft;
            params.set('scrollLeft', currentScrollLeft);  // Restore the scroll position
        }

        url.search = params.toString();
        window.location.href = url.toString();
        sessionStorage.removeItem('selectedSearchName');
        
    }


    function updateColumnVisibility() {
    
        const columnsToShow = Array.from(columnCheckboxes).filter(checkbox => checkbox.checked).map(checkbox => checkbox.getAttribute('data-column'));
        selectedColumns = columnsToShow;
        const allColumns = Array.from(columnCheckboxes).map(checkbox => checkbox.getAttribute('data-column'));
        allColumns.forEach(column => {
            const columnElements = document.querySelectorAll(`.${column}`);
            columnElements.forEach(element => {
                element.style.display = columnsToShow.includes(column) ? '' : 'none';
            });
        });

        // Update the URL with the current state of visible columns
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.set('visible_columns', selectedColumns.join(','));
        history.replaceState(null, '', `${window.location.pathname}?${urlParams.toString()}`);
        
    }


    function createFilterTag(column, term) {

        const normalizedTerm = term.toUpperCase();

        if (filterTagsDiv.querySelector(`[data-column="${column}"][data-term="${normalizedTerm}"]`)) {  // Check if a filter tag is alread existing
            return;
        }
        if (filtersContainer.contains(noFiltersMessage)) {  // Remove the "No filter" text before adding a new filter button
            filtersContainer.removeChild(noFiltersMessage);
        } 

        const tag = document.createElement('span');
        tag.classList.add('filter-tag');
        tag.textContent = `${column}: ${normalizedTerm} `;
        tag.dataset.column = column;
        tag.dataset.term = normalizedTerm;

        const removeButton = document.createElement('span');
        removeButton.classList.add('remove-tag');
        removeButton.textContent = 'x';
        removeButton.addEventListener('click', () => {
        
            filters[column] = filters[column].filter(t => t !== normalizedTerm);
            if (filters[column].length === 0) {
                delete filters[column];
            }
            
            const urlParams = new URLSearchParams(window.location.search);  // Actualize URLSearchParams to reflect the deletion

            if (filters[column] && filters[column].length > 0) {
                urlParams.set(column, filters[column].join(','));
            } else {
                urlParams.delete(column);
            }

            // Sort and order are paired: removing one removes both
            if (column === 'sort' || column === 'order') {
                const pairedKey = column === 'sort' ? 'order' : 'sort';
                urlParams.delete('sort');
                urlParams.delete('order');
                delete filters['sort'];
                delete filters['order'];
                const pairedTag = filterTagsDiv.querySelector(`[data-column="${pairedKey}"]`);
                if (pairedTag) filterTagsDiv.removeChild(pairedTag);
            }

            filterTagsDiv.removeChild(tag);  // Remove the filter Tag
            history.replaceState(null, '', `${window.location.pathname}?${urlParams.toString()}`);  // Actualize the URL without reloading the page
            applyFilters();
        });

        tag.appendChild(removeButton);
        filterTagsDiv.appendChild(tag);

    }


    function logFilters() {

        console.log("Current state of filters", JSON.stringify(filters,null,2));

    }


    function handleInput(e) {
    
        if (e.key === 'Enter' && e.target.value.trim() !== '') {
        
            e.preventDefault();
            const column = e.target.name;
            let terms;

            if (column === 'server') {
                terms = e.target.value.trim().toUpperCase().replace(/[\'"]/g, '').replace(/\s+/g, ',').replace(/;/g, ',').split(',').map(term => term.trim());
            } else {
                terms = e.target.value.trim().toUpperCase().replace(/[\'"]/g, '').split(',').map(term => term.trim());
            }

            const filtersContainer = document.getElementById('filters-container');

            if (filtersContainer.contains(noFiltersMessage)) {
                filtersContainer.removeChild(noFiltersMessage);
            }

            if (!filters[column]) {
                filters[column] = [];
            }
            
            const filtersLimit = 150;
            const currentFiltersCount = Object.values(filters).flat().length;
            const targetFiltersCount = terms.length + currentFiltersCount;
            if (targetFiltersCount > filtersLimit) {
              let s;
              if (terms.length > 1) {
                s="s";
              } else {
                s="";
              }
              alert("Adding " +  terms.length + " filter" + s + " would exceed the limit of " + filtersLimit + " filters (" + targetFiltersCount + ").\nPlease remove some filters if necessary." );
              return;
            }

            terms.forEach(term => {
                if (!filters[column].includes(term)) {
                    filters[column].push(term);
                    createFilterTag(column, term);
                }
            });

            e.target.value = '';  // Clear the search field after adding the terms
            applyFilters();
            
        }
        
    }


    function restoreColumnVisibilityFromURL() {
    
        const urlParams = new URLSearchParams(window.location.search);
        const visibleColumns = urlParams.get('visible_columns');
        
        if (visibleColumns) {
            const columns = visibleColumns.split(',');
            columnCheckboxes.forEach(checkbox => {
                checkbox.checked = columns.includes(checkbox.getAttribute('data-column'));
            });
            updateColumnVisibility();
        }
        
    }
    

    window.applyFilters = function () {
    
        // The applyFilters function is designed to take user-selected filters and other parameters, process them, and update the URL query parameters accordingly. 
        // It ensures that the filters are normalized (values converted to uppercase and duplicates removed), some specific keys are handled separately, 
        // and multiple aspects of the filter state are preserved when updating the URL.
    
        let debugMode = false;
        const searchParams = new URLSearchParams();
        
        const specialKeys = Object.values(jsonData.fields)  // Extract the listid entries from the json file: these represent the columns search dropdown boxes
        	.map(field => field.listid)
        	.filter(id => id !== undefined);

        for (const key in filters) {

            if (filters[key].length > 0) {
                const normalizedTerms = [...new Set(filters[key].map(value => value.toUpperCase()))].join(',');

                if (specialKeys.includes(key)) {
                    searchParams.set(key, normalizedTerms);
                } else {
                    searchParams.append(key, normalizedTerms);
                }
            }
        }

        if (selectedColumns.length > 0) {
            searchParams.append('visible_columns', selectedColumns.join(','));
        }

        const pageSizeSelect = document.getElementById('page_size');
        const selectedPageSize = pageSizeSelect ? pageSizeSelect.value : 50;
        searchParams.set('page_size', selectedPageSize);

        const currentParams = new URLSearchParams(window.location.search);
        for (const [key, value] of currentParams.entries()) {
            if (key.startsWith('cat_') || key === 'sort' || key === 'order') {
                searchParams.set(key, value);
            }
        }

        const urlParams = new URLSearchParams(window.location.search);
        for (const [key, value] of urlParams.entries()) {
            if (!filters[key] || filters[key].length === 0) {
                continue;
            }
            if (!searchParams.has(key)) {
                searchParams.set(key, value);
            }
        }

        if (tableContainer) {
            const currentScrollLeft = tableContainer.scrollLeft;
            searchParams.set('scrollLeft', currentScrollLeft);
        }

        if (!debugMode) {
            window.location.search = searchParams.toString();
        }

        logFilters();
        
    };


    function toggleSelectAll() {
    
        const selectAllCheckbox = document.getElementById('selectAllColumns');
        const checkboxes = document.querySelectorAll('.column-checkbox');
        const isChecked = selectAllCheckbox.checked;  // Change the state of all checkboxes based on the state of 'Select All'
        checkboxes.forEach(checkbox => {
            checkbox.checked = isChecked;
        });

        updateColumnVisibility();  // Update the visibility of the columns and apply filters after changing the state
        applyFilters();
        
    }


    function updateSelectAllState() {
    
        const selectAllCheckbox = document.getElementById('selectAllColumns');
        const checkboxes = document.querySelectorAll('.column-checkbox');
        const allChecked = Array.from(checkboxes).every(checkbox => checkbox.checked);
        const someChecked = Array.from(checkboxes).some(checkbox => checkbox.checked);

        if (allChecked) {  // Update the state of 'Select All' based on the conditions
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
        } else if (someChecked) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;  // Display the script if some are marked
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        }
        
    }
    

    function attachCategoryHandlers() {
    
        const categoryCheckboxes = document.querySelectorAll('.category-checkbox');

        categoryCheckboxes.forEach(function(catCheckbox) {
            const categoryId = catCheckbox.getAttribute('data-category');
            const content = document.getElementById(categoryId);
            if (!content) return;
            const childCheckboxes = content.querySelectorAll('.column-checkbox');

            catCheckbox.addEventListener('change', function () {  // When category checkbox changes, update only non-disabled child checkboxes
                childCheckboxes.forEach(function (child) {
                    if (!child.disabled) {
                        child.checked = catCheckbox.checked;
                    }
                    child.dispatchEvent(new Event('change'));
                });

                catCheckbox.indeterminate = false;
                 //applyFilters();
            });

            childCheckboxes.forEach(function (child) {  // When child checkboxes change, just call the clean-up function
                child.addEventListener('change', function () {
                    setTimeout(() => {
                        updateCategoryStates();
                        //applyFilters();
                    }, 0);
                });
            });

        });
        
    }


    function updateCategoryStates() {
    
        const categoryCheckboxes = document.querySelectorAll('.category-checkbox');

        categoryCheckboxes.forEach(catCheckbox => {
            const categoryId = catCheckbox.getAttribute('data-category');
            const content = document.getElementById(categoryId);

            if (!content) return;
            const childCheckboxes = content.querySelectorAll('.column-checkbox');
            const totalChildren = childCheckboxes.length;
            const checkedChildren = Array.from(childCheckboxes).filter(c => c.checked).length;

            if (checkedChildren === totalChildren) {
                catCheckbox.checked = true;
                catCheckbox.indeterminate = false;
            } else if (checkedChildren === 0) {
                catCheckbox.checked = false;
                catCheckbox.indeterminate = false;
            } else {
                catCheckbox.checked = false;
                catCheckbox.indeterminate = true;
            }
        });
        
    }


    function restoreCategoryStateFromURL() {
    
      document.querySelectorAll('.category-content').forEach(content => {
        const categoryId = content.id; // ej: "cat1"
        const urlParams = new URLSearchParams(window.location.search);
        const state = urlParams.get('cat_' + categoryId);  // It is expected that a parameter will be provided, such as cat_cat1 = "true" (expanded) or false (collapsed)
        if (state === null || state === "false") {
          content.classList.add('hidden');
        } else if (state === "true") {
          content.classList.remove('hidden');
        }
      });
      
    }


    function updateCategoryStateInURL(categoryId, isExpanded) {
    
      const url = new URL(window.location.href);
      const urlParams = url.searchParams;
      urlParams.set('cat_' + categoryId, isExpanded ? "true" : "false");  // Set the parameter 'cat_' to 'true' or 'false'
      history.replaceState(null, '', url.pathname + '?' + urlParams.toString());  // Update the URL without reloading the page
      
    }


    function attachCategoryToggleHandlers() {
    
      const categoryTitles = document.querySelectorAll('.category-title');
      categoryTitles.forEach(title => {
        title.addEventListener('click', function(e) {
          e.stopPropagation();
          const targetId = this.getAttribute('data-target');
          const content = document.getElementById(targetId);
          if (content) {
            content.classList.toggle('hidden');
            const isExpanded = !content.classList.contains('hidden');
            updateCategoryStateInURL(targetId, isExpanded);  // Update the URL with the current state of this category
          }
        });
      });
      
    }
    

    function applyPageSize() {

        const pageSizeSelect = document.getElementById('page_size');
        const selectedPageSize = pageSizeSelect.value;

        const searchParams = new URLSearchParams(window.location.search);
        searchParams.set('page_size', selectedPageSize);
        searchParams.delete('page');  // Reset the page when resizing

        window.location.search = searchParams.toString();
        
    }


    function hasActiveFilters() {
    
        const filterTags = document.querySelectorAll('.filter-tag');
        if (filterTagsDiv.length === 0) {
            filterTagsDiv.textContent = 'No filters';
            sessionStorage.removeItem('selectedSearchName');
        } else {
            //filterTagsDiv.textContent = ''; // Clear previous text if any
        }
        
        return filterTags.length > 0;
        
    }


    function validateAndShowSaveSearchModal() {
    
        if (hasActiveFilters()) {
            showSaveSearchModal()
        } else {
            alert("Please apply at least one filter before saving the search.");
        }
        
    }


    function initColumnResize() {
    
        const tableHeaders = document.querySelectorAll('th.resizable');
        const tableContainer = document.querySelector('.table-container');

        tableHeaders.forEach(header => {
        
            const resizer = document.createElement('div');
            resizer.classList.add('resizer');
            resizer.style.width = '5px';
            resizer.style.cursor = 'col-resize';
            resizer.style.position = 'absolute';
            resizer.style.right = '0';
            resizer.style.top = '0';
            resizer.style.bottom = '0';
            resizer.style.zIndex = '1';
            header.appendChild(resizer);

            resizer.addEventListener('mousedown', initResize);

            function initResize(e) {
            
                e.stopPropagation();
                e.preventDefault();
                const startX = e.clientX;
                const startWidth = header.offsetWidth;
                const initialScrollLeft = tableContainer.scrollLeft;

                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
                window.addEventListener('mousemove', resizeColumn);  // Calculate the initial scroll position and adjust the column width on mousemove
                window.addEventListener('mouseup', stopResize);

                function resizeColumn(e) {
                    const scrollDiff = tableContainer.scrollLeft - initialScrollLeft;
                    const deltaX = e.clientX - startX + scrollDiff;
                    const newWidth = startWidth + deltaX;

                    //if (newWidth > 50) {
                        header.style.width = `${newWidth}px`;
                    //}

                }

                function stopResize() {
                    window.removeEventListener('mousemove', resizeColumn);
                    window.removeEventListener('mouseup', stopResize);
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';

                    const table = document.querySelector('#serversTable');
                    if (!table) return;
                    const col1 = table.querySelectorAll('th:nth-child(1), td:nth-child(1)');
                    const col2 = table.querySelectorAll('th:nth-child(2), td:nth-child(2)');
                    const col3 = table.querySelectorAll('th:nth-child(3), td:nth-child(3)');
                    const w1 = col1[0]?.offsetWidth || 0;
                    const w2 = col2[0]?.offsetWidth || 0;
                
                    col1.forEach(cell => cell.style.left = '0px');
                    col2.forEach(cell => cell.style.left = w1 + 'px');
                    col3.forEach(cell => cell.style.left = (w1 + w2) + 'px');

                }
            
            }
            
        });
        
    }

 
    /* --  Elements Events and Actions -- */

    columnCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', function () {
            updateColumnVisibility();
        });
    });


    searchInputs.forEach(input => {  // Actions on input fields 
        input.addEventListener('keyup', handleInput);
    });


    if (selectAllCheckbox) {
       selectAllCheckbox.addEventListener('change', toggleSelectAll);
    }


    if (clearFiltersButton) {
        clearFiltersButton.addEventListener('click', clearFilters);
    }
    
    
    Object.keys(elements).forEach(key => {  // For each listbox filter and input filter
        if (key.endsWith('Listbox')) {
            const listbox = elements[key];
            const baseName = key.replace('Listbox', '');
            const input = elements[`${baseName}Input`];

            if (listbox && input) {
                listbox.addEventListener('change', function() {
                    const selectedValue = listbox.value.toUpperCase();

                    if (selectedValue) {
                        input.value = '';
                        const selectedValueStrict = '@' + selectedValue;

                        if (!filters[baseName]) {
                            filters[baseName] = [];
                        }

                        if (!filters[baseName].includes(selectedValueStrict)) {
                            filters[baseName].push(selectedValueStrict);
                        }

                        const urlParams = new URLSearchParams(window.location.search);
                        urlParams.delete(baseName);

                        filters[baseName].forEach(value => {
                            createFilterTag(baseName, value);
                            console.log(value);
                        });

                        urlParams.set(baseName, filters[baseName].join(','));
                        history.replaceState(null, '', `${window.location.pathname}?${urlParams.toString()}`);
                        applyFilters();
                    }
                });

                const urlParams = new URLSearchParams(window.location.search);  // Handle URL parameters for this listbox
                const paramValue = urlParams.get(baseName);

                if (paramValue) {
                    listbox.value = paramValue;
                    input.value = paramValue;
                    input.value = ''; // Clear the input value
                }
            }
        }
        
    });


    /* --  Rebuild the interface -- */

    restoreColumnVisibilityFromURL();
    updateColumnVisibility();
    attachCategoryHandlers();  // Attach handlers to the category checkboxes
    updateCategoryStates();  // Recalculate category states (to show 'indeterminate' if necessary)
    restoreCategoryStateFromURL()
    attachCategoryToggleHandlers()


	if (saveSearchForm) {
	
		saveSearchForm.addEventListener('submit', function(event) {
        	event.preventDefault();
        	const searchParams = new URLSearchParams(window.location.search);
        	const filters = Object.fromEntries(searchParams.entries());

        	if (Object.keys(filters).length === 0) {
            	alert("No filters are selected. Please select at least one filter.");
            	return;
        	}
        	
        	const inputName = document.getElementById('search_name');
            const chosenName = inputName.value.trim();
            if (chosenName.length > 25) {
                alert("Search name must be less than 25 characters.");
                return;
            }
            if (savedSearchNames.includes(chosenName)) {
                event.preventDefault();
                alert("A search with this name already exists.");
                return;
            }
        	
        	document.getElementById('filtersInput').value = JSON.stringify(filters);

        	const tags = [];
        	filterTagsDiv.querySelectorAll('.filter-tag').forEach(tag => {
            	tags.push(tag.dataset.column + ':' + tag.dataset.term);
        	});
        	document.getElementById('tagsInput').value = JSON.stringify(tags);
        	saveSearchForm.submit();
    	});
    	
	}


    const urlParams = new URLSearchParams(window.location.search);
    for (const [key, value] of urlParams.entries()) {
        if (key !== 'page' && key !== 'visible_columns' && key !== 'page_size' && key !== 'scrollLeft' && (!key.startsWith('cat_'))) {
            if (!filters[key]) {
                filters[key] = [];
            }
            const terms = value.split(',').map(term => term.trim().toUpperCase());
            terms.forEach(term => {
                if (!filters[key].includes(term)) {
                    filters[key].push(term);
                    createFilterTag(key, term);
                }
            });
        }
    }

    updateColumnVisibility();

    window.toggleSelectAll = toggleSelectAll;
    window.updateSelectAllState = updateSelectAllState;
    window.applyPageSize = applyPageSize;  // Make it globally accessible
    window.validateAndShowSaveSearchModal = validateAndShowSaveSearchModal;  // Make it globally accessible

    initColumnResize();
    updateSelectAllState();


    /* --  Restore the scroll position if it comes in the URL -- */

    {
        const urlParams = new URLSearchParams(window.location.search);
        const storedScrollLeft = urlParams.get('scrollLeft');
        if (storedScrollLeft && tableContainer) {
            const scrollLeftValue = parseInt(storedScrollLeft, 10);
            if (!isNaN(scrollLeftValue)) {
                tableContainer.scrollLeft = scrollLeftValue;
            }
            urlParams.delete('scrollLeft');  // Remove scrollLeft from the URL to avoid perpetuating it
            history.replaceState(null, '', window.location.pathname + '?' + urlParams.toString());
        }
    }

});
