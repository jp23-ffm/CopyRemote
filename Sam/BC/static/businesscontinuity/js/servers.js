document.addEventListener('DOMContentLoaded', function () {  // Wait for the DOM to be fully loaded before executing the script

    // Get needed references
    const editModalOverlay = document.getElementById('editModalOverlay');
    const closeModalButton = document.getElementById('closeModalButton');
    const cancelModalButton = document.getElementById('cancelModalButton');
    const editForm = document.getElementById('editForm');
    var serversTable = document.getElementById('serversTable');
    var userCanEdit = serversTable.dataset.userCanedit === 'True';

    if (userCanEdit) {

        // Close button inside bulk edit modal
        const bulkModalClose = document.getElementById('bulkEditModal')
                                       .querySelector('.close-button');
        if (bulkModalClose) {
            bulkModalClose.addEventListener('click', closeBulkModal);
        }

        // Standalone bulk edit button — may no longer exist if grouped under Edit dropdown
        const bulkEditBtn = document.getElementById('bulkEditButton');
        if (bulkEditBtn) {
            bulkEditBtn.addEventListener('click', function () {
                document.getElementById('bulkEditModal').style.display = 'flex';
            });
        }

    }

    
    // Check the stored value of a YES/NO/EMPTY field; an unknown value checks nothing and is kept on save
    function setEditChoice(name, value) {
        const wanted = (value || '').trim().toUpperCase();
        document.querySelectorAll(`#editForm input[name="${name}"]`).forEach(radio => {
            radio.checked = radio.value === wanted;
        });
    }


    function openModal() {  // Open the edit modal and focus on the first input field in the form
        editModalOverlay.style.display = 'flex';
        const firstInput = document.querySelector('#editForm input[name="priority_asset"]:checked')
            || document.querySelector('#editForm input[name="priority_asset"]');
        if (firstInput) firstInput.focus();
    }

    
    function closeModal() {  // Close the edit modal
        editModalOverlay.style.display = 'none';
    }

    
    document.querySelectorAll('.edit-button').forEach(button => {  // Add an event listener to each edit button

        button.addEventListener('click', function () {

            currentServerId = this.dataset.serverId;
            const editForm = document.getElementById('editForm');
            const historyContainer = document.getElementById('historyContainer');
            if (historyContainer.style.display === 'block') {
                historyContainer.style.display = 'none';
                editForm.style.display = 'block';
                document.getElementById('historyButton').style.display = 'inline-block';
            }

            const hostnameUnique = this.dataset.serverId;  // Get the hostname unique ID from the button's dataset
            const row = this.closest('tr');  // Get the row that the button is in
            const priorityAsset = row.dataset.priorityAsset;  // Get the values for the row from the dataset
            const inLivePlay = row.dataset.inLivePlay;
            const actionDuringLp = row.dataset.actionDuringLp;
            const actionDuringLpHistory = row.dataset.actionDuringLpHistory;
            const actionDuringLpHistoryLines = actionDuringLpHistory.split('\n').filter(line => !line.includes('EMPTY'));
            const annotation = row.dataset.annotation;
            const annotationHistory = row.dataset.annotationHistory;
            const annotationHistoryLines = annotationHistory.split('\n').filter(line => !line.includes('EMPTY'));
            const cluster = row.dataset.cluster;
            const clusterType = row.dataset.clusterType;
            const bcException = row.dataset.bcException;

            // Inject the values into the edit form
            document.getElementById('editModalLabel').innerText = `Edit the information for ${hostnameUnique}`;
            setEditChoice('priority_asset', priorityAsset);
            setEditChoice('in_live_play', inLivePlay);
            document.getElementById('id_action_during_lp').value = actionDuringLp === 'EMPTY' ? '' : actionDuringLp;
            document.getElementById('id_annotation_history').value = annotationHistoryLines.join('\n');
            document.getElementById('id_annotation').value = annotation === 'EMPTY' ? '' : annotation;
            document.getElementById('id_action_during_lp_history').value = actionDuringLpHistoryLines.join('\n');
            setEditChoice('cluster', cluster);
            document.getElementById('id_cluster_type').value = clusterType === 'EMPTY' ? '' : clusterType;
            setEditChoice('bc_exception', bcException);

            if (!userCanEdit) {
                // Set all input fields to readonly
                document.querySelectorAll('#editForm input, #editForm select, #editForm textarea').forEach(field => {
                    field.readOnly = true;
                    field.disabled = true; // Disable select and textarea fields
                });
                document.querySelector('#editForm button[type="submit"]').style.display = 'none';
                document.querySelector('#editForm .btn-secondary').innerText = 'Close';
            }
            else {
                editForm.action = `/${appname}/edit/${hostnameUnique}/`;  // Set the form action to the edit URL for the hostname unique ID
            }
            
            openModal();
            
        });

    });

    
    closeModalButton.addEventListener('click', function () {  // Event listener to the close button in the edit modal
        closeModal();
        closeBulkModal();
    });

    
    cancelModalButton.addEventListener('click', function () {  // Event listener to the cancel button in the edit modal
        closeModal();
        closeBulkModal();
    });

    
    editModalOverlay.addEventListener('click', function (event) {  // Event listener to the edit modal overlay: If the user clicks on the overlay, close the modal
        if (event.target === editModalOverlay) {
            closeModal();
        }
    });

    
    document.getElementById('bulkEditModal').addEventListener('click', function (event) {  // Event listener to the bulk edit modal: If the user clicks on the modal background, close the modal
        if (event.target === this) {
            closeBulkModal();
        }
    });

    
    document.getElementById('bulkEditModal').querySelector('.btn-secondary').addEventListener('click', closeBulkModal);  // Event listener to the secondary button in the bulk edit modal


    document.addEventListener('keydown', function (e) {  // Event listener for the Escape key
        if (e.key === 'Escape') {
            closeModal();
            closeBulkModal();
        }
    });
    

    document.getElementById('historyButton').addEventListener('click', function() {
    
        const editForm = document.getElementById('editForm');
        const historyContainer = document.getElementById('historyContainer');
        const historyButton = document.getElementById('historyButton');

        // Display the historic
        historyContainer.style.display = 'block';
        editForm.style.display = 'none';
        historyButton.style.display = 'none';

        // Get the current server ID
        const serverId = currentServerId

        const fieldNames = {
            "priority_asset": "Priority Asset",
            "in_live_play": "In Live Play",
            "action_during_lp": "Action During LP",
            "annotation": "Annotation",
            "cluster": "Cluster",
            "cluster_type": "Cluster Type",
            "bc_exception": "BC Exception",
            "history_wiped": "History"
        };

        // Get the historic data from the server
        fetch(`${getServerHistoryUrl}?server_id=${serverId}`)
            .then(response => response.json())
            .then(data => {
                const historyList = document.getElementById('historyList');
                historyList.innerHTML = '';

                // Sort the historic entries by descending date
                data.sort((a, b) => new Date(b.date) - new Date(a.date));

                data.forEach(entry => {
                    const listItem = document.createElement('li');
                    listItem.classList.add('history-entry');
                    listItem.textContent = `${entry.date} - ${entry.user} - ${entry.fromsource}`;
                    const changesList = document.createElement('ul');
                    changesList.classList.add('changes-list');
                    Object.keys(entry.changes).forEach(field => {
                        const changeItem = document.createElement('li');
                        changeItem.classList.add('change-item');
                        if (entry.changes[field].info) {
                                changeItem.textContent = `${fieldNames[field]}: ${entry.changes[field].info}`;
                            } else {
                                changeItem.textContent = `${fieldNames[field]}: ${entry.changes[field].new} (was ${entry.changes[field].old})`;
                            }
                        changesList.appendChild(changeItem);
                    });
                    listItem.appendChild(changesList);
                    historyList.appendChild(listItem);
                });
            });

    });


    document.getElementById('backToEditButton').addEventListener('click', function() {
        const editForm = document.getElementById('editForm');
        const historyContainer = document.getElementById('historyContainer');
        const historyButton = document.getElementById('historyButton');

        // Display the edit form
        historyContainer.style.display = 'none';
        editForm.style.display = 'block';
        historyButton.style.display = 'inline-block';
        
    }); 
    

});


