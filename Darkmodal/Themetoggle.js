// common/static/common/js/theme-toggle.js

// Charger le thème au chargement de la page
async function loadTheme() {
    try {
        const response = await fetch('/common/api/preferences/?app=global');
        const data = await response.json();
        
        if (data.success && data.settings.theme) {
            applyTheme(data.settings.theme);
        } else {
            // Par défaut, utiliser la préférence système
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            applyTheme(prefersDark ? 'dark' : 'light');
        }
    } catch (error) {
        console.error('Error loading theme:', error);
    }
}

// Appliquer le thème
function applyTheme(theme) {
    if (theme === 'dark') {
        document.documentElement.classList.add('dark-mode');
    } else {
        document.documentElement.classList.remove('dark-mode');
    }
}

// Toggle et sauvegarder
async function toggleTheme() {
    const isDark = document.documentElement.classList.contains('dark-mode');
    const newTheme = isDark ? 'light' : 'dark';
    
    // Appliquer immédiatement
    applyTheme(newTheme);
    
    // Sauvegarder en base
    try {
        await fetch('/common/api/preferences/update/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                app_name: 'global',
                key: 'theme',
                value: newTheme
            })
        });
    } catch (error) {
        console.error('Error saving theme:', error);
    }
}

// Charger au démarrage
document.addEventListener('DOMContentLoaded', loadTheme);

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}
