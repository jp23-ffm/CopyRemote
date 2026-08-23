let currentHostname = null;
let pendingReload = false;
let addFormVisible = true;
let historyVisible = false;

function editAnnotation(hostname) {
    currentHostname = hostname;
    pendingReload = false;

    document.getElementById('annotationModal').style.display = 'flex';
    document.getElementById('annotation-hostname-display').textContent = hostname;
    document.getElementById('modal-hostname').value = hostname;

    _resetAddForm();

    fetch(`/inventory/annotation/${encodeURIComponent(hostname)}/`)
        .then(r => r.json())
        .then(data => {
            const history = data.history || [];
            displayHistory(history);
            _applyInitialLayout(history.length > 0);
        })
        .catch(() => alert('Error loading annotations'));
}

function _applyInitialLayout(hasAnnotations) {
    const addForm = document.getElementById('annotation-add-form');
    const toggleBtn = document.getElementById('toggle-add-btn');
    const historySection = document.getElementById('history-section');
    const historyBtn = document.getElementById('history-toggle-btn');

    addFormVisible = !hasAnnotations;
    historyVisible = hasAnnotations;

    if (addForm) addForm.style.display = addFormVisible ? 'block' : 'none';
    if (toggleBtn) toggleBtn.innerHTML = addFormVisible ? '&#9660; Hide' : '&#9654; Show';
    if (historySection) historySection.style.display = historyVisible ? 'block' : 'none';
    if (historyBtn) historyBtn.innerHTML = historyVisible ? '&#9660; Hide annotations' : '&#9654; Show annotations';
}

function saveAnnotation() {
    if (!currentHostname) return;

    const notes = document.getElementById('annotation-notes').value.trim();
    const type = document.getElementById('annotation-type').value;
    const customType = document.getElementById('custom-type').value.trim();
    const servicenow = document.getElementById('annotation-servicenow').value.trim();

    if (!notes) return;

    const finalType = type === 'CUSTOM' ? customType : type;
    const btn = document.querySelector('#annotation-add-form .btn-save');
    btn.disabled = true;
    btn.textContent = 'Saving...';

    fetch(`/inventory/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCsrfToken()},
        body: `action=add&notes=${encodeURIComponent(notes)}&type=${encodeURIComponent(finalType)}&servicenow=${encodeURIComponent(servicenow)}`
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            _resetAddForm();
            displayHistory(data.history || []);
            pendingReload = true;
        } else {
            alert('Error: ' + data.message);
        }
    })
    .catch(() => alert('Connection error'))
    .finally(() => {
        btn.disabled = false;
        btn.textContent = 'Save';
    });
}

function closeAnnotationModal() {
    document.getElementById('annotationModal').style.display = 'none';
    currentHostname = null;
    _resetAddForm();
    if (pendingReload) {
        pendingReload = false;
        window.location.reload();
    }
}

function toggleAddForm() {
    const form = document.getElementById('annotation-add-form');
    const btn = document.getElementById('toggle-add-btn');
    addFormVisible = !addFormVisible;
    form.style.display = addFormVisible ? 'block' : 'none';
    btn.innerHTML = addFormVisible ? '&#9660; Hide' : '&#9654; Show';
}

function toggleHistory() {
    const section = document.getElementById('history-section');
    const btn = document.getElementById('history-toggle-btn');
    historyVisible = !historyVisible;
    section.style.display = historyVisible ? 'block' : 'none';
    btn.innerHTML = historyVisible ? '&#9660; Hide annotations' : '&#9654; Show annotations';
}

function displayHistory(history) {
    const container = document.getElementById('annotation-history');
    const emptyMsg = document.getElementById('no-annotations-msg');
    container.innerHTML = '';

    if (!history || history.length === 0) {
        if (emptyMsg) emptyMsg.style.display = 'block';
        return;
    }
    if (emptyMsg) emptyMsg.style.display = 'none';

    history.forEach(entry => {
        const div = document.createElement('div');
        div.className = 'history-entry';

        const date = new Date(entry.date);
        const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});

        div.innerHTML = `
            <div class="history-meta">
                <strong>${escapeHtml(entry.user || '')}</strong> &bull; ${formattedDate}
            </div>
            <div class="history-text">
                <strong>[${escapeHtml(entry.type || 'N/A')}]</strong>
                ${entry.servicenow ? `<span class="annotation-ritm">${escapeHtml(entry.servicenow)}</span>` : ''}
                ${escapeHtml(entry.text || '')}
            </div>
        `;
        container.appendChild(div);
    });
}

function _resetAddForm() {
    const typeSelect = document.getElementById('annotation-type');
    const customType = document.getElementById('custom-type');
    if (typeSelect) typeSelect.value = '';
    if (customType) { customType.style.display = 'none'; customType.value = ''; }
    const servicenow = document.getElementById('annotation-servicenow');
    const notes = document.getElementById('annotation-notes');
    if (servicenow) servicenow.value = '';
    if (notes) notes.value = '';

    // Ensure add form is visible, history collapsed
    const addForm = document.getElementById('annotation-add-form');
    const toggleBtn = document.getElementById('toggle-add-btn');
    const historySection = document.getElementById('history-section');
    const historyBtn = document.getElementById('history-toggle-btn');
    if (addForm) addForm.style.display = 'block';
    if (toggleBtn) toggleBtn.innerHTML = '&#9660; Hide';
    if (historySection) historySection.style.display = 'none';
    if (historyBtn) historyBtn.innerHTML = '&#9654; Show annotations';
    addFormVisible = true;
    historyVisible = false;
}

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function getCsrfToken() {
    for (let cookie of document.cookie.split(';')) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') return value;
    }
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

document.addEventListener('click', function (event) {
    const modal = document.getElementById('annotationModal');
    if (event.target === modal) closeAnnotationModal();
});

document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        const modal = document.getElementById('annotationModal');
        if (modal && modal.style.display === 'flex') closeAnnotationModal();
    }
});
