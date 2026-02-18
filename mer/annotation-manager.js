let currentHostname = null;

function editAnnotation(hostname) {
    currentHostname = hostname;

    document.getElementById('annotationModal').style.display = 'flex';
    document.getElementById('modal-hostname').value = hostname;

    fetch(`/discrepancies/annotation/${encodeURIComponent(hostname)}/`)
        .then(response => response.json())
        .then(data => {
            document.getElementById('annotation-comment').value = data.comment || '';
            document.getElementById('annotation-assigned-to').value = data.assigned_to || '';
            displayHistory(data.history);
        })
        .catch(error => {
            console.error('[Annotation] Error loading:', error);
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
                <strong>${escapeHtml(entry.user)}</strong> - ${formattedDate}
            </div>
            <div class="history-text">
                <strong>Assigned To:</strong> ${escapeHtml(entry.assigned_to || 'N/A')}<br>
                <strong>Comment:</strong> ${escapeHtml(entry.comment)}
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
}

function saveAnnotation() {
    if (!currentHostname) {
        alert('Error: no server selected');
        return;
    }

    const comment = document.getElementById('annotation-comment').value.trim();
    const assignedTo = document.getElementById('annotation-assigned-to').value.trim();

    const saveBtn = document.querySelector('.btn-save');
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    fetch(`/discrepancies/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': getCsrfToken()
        },
        body: `comment=${encodeURIComponent(comment)}&assigned_to=${encodeURIComponent(assignedTo)}`
    })
    .then(response => response.json())
    .then(data => {
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

    const confirmClear = window.confirm('Are you sure you want to clear the annotation?');
    if (!confirmClear) {
        return;
    }

    const saveBtn = document.querySelector('.btn-save');
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    fetch(`/discrepancies/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': getCsrfToken()
        },
        body: `comment=&assigned_to=`
    })
    .then(response => response.json())
    .then(data => {
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
