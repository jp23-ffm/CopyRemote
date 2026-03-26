let currentHostname = null;

function editAnnotation(hostname) {
    currentHostname = hostname;

    document.getElementById('annotationModal').style.display = 'flex';
    document.getElementById('modal-hostname').value = hostname;

    fetch(`/inventory/annotation/${encodeURIComponent(hostname)}/`)
        .then(response => response.json())
        .then(data => {
            document.getElementById('annotation-notes').value = data.notes || '';
            document.getElementById('annotation-servicenow').value = data.servicenow || '';
            displayHistory(data.history);

            const typeSelect = document.getElementById('annotation-type');
            const knownTypes = Array.from(typeSelect.options)
                                    .map(o => o.value)
                                    .filter(v => v !== 'CUSTOM');
            const type = data.type || '';
            const customTypeGroup = document.getElementById('custom-type-group');
            const customTypeInput = document.getElementById('custom-type');

            if (!type || knownTypes.includes(type)) {
                typeSelect.value = type;
                customTypeGroup.style.display = 'none';
                customTypeInput.value = '';
            } else {
                // Unknown type → show as CUSTOM with the stored value in the text field
                typeSelect.value = 'CUSTOM';
                customTypeGroup.style.display = 'block';
                customTypeInput.value = type;
            }
        })
        .catch(error => {
            alert('Error loading annotation');
        });
}

function displayHistory(history) {
    const historySection = document.getElementById('history-section');
    const historyContainer = document.getElementById('annotation-history');

    if (!history || history.length === 0) {
        historySection.style.display = 'none';
        return;
    }

    historySection.style.display = 'block';
    historyContainer.innerHTML = '';

    history.forEach(entry => {
        const entryDiv = document.createElement('div');
        entryDiv.className = 'history-entry';

        const date = new Date(entry.date);
        const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();

        entryDiv.innerHTML = `
            <div class="history-meta">
                <strong>${entry.user}</strong> - ${formattedDate}
            </div>
            <div class="history-text">
                <strong>Type:</strong> ${entry.type || 'N/A'}<br>
                <strong>ServiceNow:</strong> ${entry.servicenow || 'N/A'}<br>
                <strong>Note:</strong> ${escapeHtml(entry.text)}
            </div>
        `;

        historyContainer.appendChild(entryDiv);
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function closeAnnotationModal() {
    document.getElementById('annotationModal').style.display = 'none';
    currentHostname = null;
    document.getElementById('annotationForm').reset();
    document.getElementById('history-section').style.display = 'none';
    document.getElementById('custom-type-group').style.display = 'none'; // Hide custom type field
}

function saveAnnotation() {
    if (!currentHostname) {
        alert('Error: no server selected');
        return;
    }

    const notes = document.getElementById('annotation-notes').value.trim();
    const type = document.getElementById('annotation-type').value;
    const customType = document.getElementById('custom-type').value.trim();
    const servicenow = document.getElementById('annotation-servicenow').value.trim();

    if (!notes) {
        return;
    }

    const saveBtn = document.querySelector('.btn-save');
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    const finalType = type === 'CUSTOM' ? customType : type;

    fetch(`/inventory/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': getCsrfToken()
        },
        body: `notes=${encodeURIComponent(notes)}&type=${encodeURIComponent(finalType)}&servicenow=${encodeURIComponent(servicenow)}`
    })
    .then(response => response.json())
    .then(data => {
        console.log(data);
        if (data.success) {
            closeAnnotationModal();
            window.location.reload();
        } else {
            console.error('[Annotation] Error:', data.message);
            alert('Error: ' + data.message);
        }
    })
    .catch(error => {
        console.error('[Annotation] Network error:', error);
        alert('Connection error during save');
    })
    .finally(() => {
        saveBtn.disabled = false;
        saveBtn.textContent = originalText;
    });
}


function clearAnnotation() {

    if (!currentHostname) {
        alert('Error: no server selected');
        return;
    }
    
    const confirmClear = window.confirm('Are you really sure to revert the current values to EMPTY ?');
    if (!confirmClear) {
        return;
    }

    const saveBtn = document.querySelector('.btn-save');
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    fetch(`/inventory/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': getCsrfToken()
        },
        body: `notes=&type=&servicenow=`
    })
    .then(response => response.json())
    .then(data => {
        console.log(data);
        if (data.success) {
            closeAnnotationModal();
            window.location.reload();
        } else {
            console.error('[Annotation] Error:', data.message);
            alert('Error: ' + data.message);
        }
    })
    .catch(error => {
        console.error('[Annotation] Network error:', error);
        alert('Connection error during save');
    })
    .finally(() => {
        saveBtn.disabled = false;
        saveBtn.textContent = originalText;
    });
    
}


function getCsrfToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return value;
        }
    }

    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag) {
        return metaTag.getAttribute('content');
    }

    console.warn('[Annotation] CSRF token not found');
    return '';
}

document.addEventListener('click', function(event) {
    const modal = document.getElementById('annotationModal');
    if (event.target === modal) {
        closeAnnotationModal();
    }
});

document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const modal = document.getElementById('annotationModal');
        if (modal && modal.style.display === 'flex') {
            closeAnnotationModal();
        }
    }
});

