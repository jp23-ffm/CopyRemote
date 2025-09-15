// static/myapp/js/annotation-manager.js

let currentHostname = null;

function editAnnotation(hostname) {
    currentHostname = hostname;
    console.log('[Annotation] Editing:', hostname);
    
    // Show modal first
    document.getElementById('annotationModal').style.display = 'flex';

    // Then fill the hostname
    document.getElementById('modal-hostname').value = hostname;
    
    // Load existing data
    fetch(`/serversgroups/annotation/${encodeURIComponent(hostname)}/`)
        .then(response => response.json())
        .then(data => {
            // Fill the rest of the form
            document.getElementById('status').value = data.status;
            document.getElementById('custom_status').value = data.custom_status;
            document.getElementById('notes').value = data.notes;
            document.getElementById('priority').value = data.priority;
            
            // Show/hide custom status field
            //toggleCustomStatus();
        })
        .catch(error => {
            console.error('[Annotation] Error loading:', error);
            alert('Error loading annotation');
        });
}

function toggleCustomStatus() {
    const statusSelect = document.getElementById('status');
    const customGroup = document.getElementById('customStatusGroup');
    const customInput = document.getElementById('custom_status');
    
    if (statusSelect.value === 'custom') {
        customGroup.style.display = 'block';
        customInput.required = true;
    } else {
        customGroup.style.display = 'none';
        customInput.required = false;
        customInput.value = '';
    }
}

function closeAnnotationModal() {
    document.getElementById('annotationModal').style.display = 'none';
    currentHostname = null;
    
    // Reset the form
    document.getElementById('annotationForm').reset();
    toggleCustomStatus();
}

function saveAnnotation() {
    if (!currentHostname) {
        alert('Error: no server selected');
        return;
    }
    
    // Validation
    const status = document.getElementById('status').value;
    const customStatus = document.getElementById('custom_status').value;
    
    if (status === 'custom' && !customStatus.trim()) {
        alert('Please enter a custom status');
        document.getElementById('custom_status').focus();
        return;
    }
    
    // Prepare data
    const formData = {
        status: status,
        custom_status: customStatus,
        notes: document.getElementById('notes').value,
        priority: document.getElementById('priority').value
    };
    
    console.log('[Annotation] Saving:', currentHostname, formData);
    
    // Disable button during save
    const saveBtn = document.querySelector('.btn-save');
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    
    // Send data
    fetch(`/serversgroups/annotation/${encodeURIComponent(currentHostname)}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log('[Annotation] Saved successfully');
            
            // Close modal
            closeAnnotationModal();
            
            // Reload page to see changes
            // Or update display dynamically
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
        // Re-enable button
        saveBtn.disabled = false;
        saveBtn.textContent = originalText;
    });
}

function getCsrfToken() {
    // Get CSRF token from cookies or meta tag
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            return value;
        }
    }
    
    // Fallback: look in meta tag
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag) {
        return metaTag.getAttribute('content');
    }
    
    console.warn('[Annotation] CSRF token not found');
    return '';
}

// Close modal by clicking outside
document.addEventListener('click', function(event) {
    const modal = document.getElementById('annotationModal');
    if (event.target === modal) {
        closeAnnotationModal();
    }
});

// Close modal with Escape key
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const modal = document.getElementById('annotationModal');
        if (modal && modal.style.display === 'flex') {
            closeAnnotationModal();
        }
    }
});

// Initialization
document.addEventListener('DOMContentLoaded', function() {
    console.log('[Annotation] Annotation manager initialized');
    
    // Add event listeners for forms
    const form = document.getElementById('annotationForm');
    if (form) {
        form.addEventListener('submit', function(event) {
            event.preventDefault();
            saveAnnotation();
        });
    }
});