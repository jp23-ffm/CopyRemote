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
            renderActiveAnnotations(data.active_annotations || []);
            displayHistory(data.history || []);
        })
        .catch(() => alert('Error loading annotations'));
}

function renderActiveAnnotations(annotations) {
    const list = document.getElementById('active-annotations-list');
    const emptyMsg = document.getElementById('no-annotations-msg');
    const resolveAllBtn = document.getElementById('resolve-all-btn');

    list.innerHTML = '';

    if (!annotations || annotations.length === 0) {
        emptyMsg.style.display = 'block';
        resolveAllBtn.style.display = 'none';
        return;
    }

    emptyMsg.style.display = 'none';
    resolveAllBtn.style.display = annotations.length > 1 ? 'inline-block' : 'none';

    annotations.forEach(entry => {
        const typeRaw = entry.type || '';
        const typeSafe = typeRaw.replace(/[^a-zA-Z0-9]/g, '') || 'OTHER';
        const card = document.createElement('div');
        card.className = `annotation-card ann-type-${typeSafe}`;

        const date = new Date(entry.date);
        const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        const ritmHtml = entry.servicenow
            ? `<span class="annotation-ritm">${escapeHtml(entry.servicenow)}</span>`
            : '';

        card.innerHTML = `
            <div class="annotation-card-header">
                <span class="annotation-type-badge type-${typeSafe}">${escapeHtml(typeRaw || 'N/A')}</span>
                ${ritmHtml}
                <span class="annotation-card-meta">${escapeHtml(entry.user || '')} &bull; ${formattedDate}</span>
                <button class="annotation-resolve-btn" onclick="resolveAnnotation(${entry.index})" title="Mark as resolved">&#10003; Resolve</button>
            </div>
            <div class="annotation-card-body">${escapeHtml(entry.text || '')}</div>
        `;
        list.appendChild(card);
    });
}

function resolveAnnotation(entryIndex) {
    if (!currentHostname) return;

    fetch(`/inventory/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCsrfToken()},
        body: `action=resolve&entry_index=${entryIndex}`
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            renderActiveAnnotations(data.active_annotations || []);
            displayHistory(data.history || []);
            pendingReload = true;
        } else {
            alert('Error: ' + data.message);
        }
    })
    .catch(() => alert('Connection error'));
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
            renderActiveAnnotations(data.active_annotations || []);
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

function clearAllAnnotations() {
    if (!currentHostname) return;
    if (!confirm('Resolve all active annotations for this server?')) return;

    fetch(`/inventory/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': getCsrfToken()},
        body: 'action=clear'
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            renderActiveAnnotations([]);
            displayHistory(data.history || []);
            pendingReload = true;
        } else {
            alert('Error: ' + data.message);
        }
    })
    .catch(() => alert('Connection error'));
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
    btn.innerHTML = historyVisible ? '&#9660; Hide history' : '&#9654; Show history';
}

function displayHistory(history) {
    const container = document.getElementById('annotation-history');
    container.innerHTML = '';

    if (!history || history.length === 0) return;

    history.forEach(entry => {
        const div = document.createElement('div');
        const isResolved = entry.is_active === false;
        div.className = 'history-entry' + (isResolved ? ' history-entry-resolved' : '');

        const date = new Date(entry.date);
        const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        const resolvedInfo = isResolved && entry.resolved_by
            ? ` &mdash; resolved by <strong>${escapeHtml(entry.resolved_by)}</strong>`
            : '';

        div.innerHTML = `
            <div class="history-meta">
                <strong>${escapeHtml(entry.user || '')}</strong> &bull; ${formattedDate}${resolvedInfo}
                ${isResolved ? '<span class="history-resolved-badge">resolved</span>' : ''}
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
    if (historyBtn) historyBtn.innerHTML = '&#9654; Show history';
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
