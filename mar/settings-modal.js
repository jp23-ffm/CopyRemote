let currentAppNameSettings = 'inventory';

function initSettingsModal(appName) {
    currentAppNameSettings = appName;
    initDarkMode();
    if (appName === 'discrepancies') {
        const pfModeSetting = document.getElementById('pf-mode-setting');
        const pfModeDivider = document.getElementById('pf-mode-divider');
        if (pfModeSetting) pfModeSetting.style.display = '';
        if (pfModeDivider) pfModeDivider.style.display = '';
        const pfModeToggle = document.getElementById('pfModeToggle');
        if (pfModeToggle) pfModeToggle.checked = getPfMode() === 'multi';
    }
}

function getPfMode() {
    return localStorage.getItem('pf_mode_discrepancies') || 'multi';
}

function setPfMode(mode) {
    localStorage.setItem('pf_mode_discrepancies', mode);
}

function togglePfMode() {
    const toggle = document.getElementById('pfModeToggle');
    const newMode = toggle.checked ? 'multi' : 'single';
    setPfMode(newMode);
    if (typeof onPfModeChange === 'function') {
        onPfModeChange(newMode);
    }
}


  function initDarkMode() {
      const isDarkMode = localStorage.getItem('darkMode') === 'true';
      const toggle = document.getElementById('themeToggle');
      if (isDarkMode) {
        document.documentElement.setAttribute('data-theme', 'dark-mode');
        if (toggle) {
            toggle.checked = true;
        }
      }
  }


  function toggleDarkMode() {
      const toggle = document.getElementById('themeToggle');  // darkModeToggle
      const isDarkMode = toggle.checked;
      
      if (isDarkMode) {
          document.documentElement.setAttribute('data-theme', 'dark-mode');
          localStorage.setItem('darkMode', 'true');
      } else {
          document.documentElement.removeAttribute('data-theme');
          localStorage.setItem('darkMode', 'false');
      }
  }


  function openSettingsModal() {
    const modal = document.getElementById('settingsModal');
    modal.classList.add('show');
    document.body.style.overflow = 'hidden';

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark-mode';
    document.getElementById('themeToggle').checked = isDark;
  }


function toggleThemeFromSettings() {
    /*const checkbox = document.getElementById('themeToggle');
    const newTheme = checkbox.checked ? 'dark' : 'light';
    applyTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    saveSettingToDB('theme', newTheme);*/
    
    const toggle = document.getElementById('themeToggle');
    const isDarkMode = toggle.checked;
      
    if (isDarkMode) {
        document.documentElement.setAttribute('data-theme', 'dark-mode');
        localStorage.setItem('darkMode', 'true');
    } else {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('darkMode', 'false');
    }
}

function closeSettingsModal() {

    const modal = document.getElementById('settingsModal');
    modal.classList.remove('show');
    document.body.style.overflow = '';
    
}

    
async function loadAllSettings() {
    try {

        const globalResponse = await fetch('/common/api/preferences/?app=global');
        const globalData = await globalResponse.json();
        
        if (globalData.success && globalData.settings) {
            if (globalData.settings.theme) {
                const isDark = globalData.settings.theme === 'dark';
                document.getElementById('themeToggle').checked = isDark;
            }
        }
        
        const appResponse = await fetch(`/common/api/preferences/?app=${currentAppNameSettings}`);
        const appData = await appResponse.json();
        
        
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}


async function saveSettingToDB(key, value, appName = 'global') {
    try {
        await fetch('/common/api/preferences/update/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                app_name: appName,
                key: key,
                value: value
            })
        });
    } catch (error) {
        console.error('Error saving setting:', error);
    }
}
    

// Event listeners

document.addEventListener('DOMContentLoaded', function() {

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const modal = document.getElementById('settingsModal');
            if (modal && modal.classList.contains('show')) {
                closeSettingsModal();
            }
        }
    });

    document.addEventListener('click', function(e) {
        const modal = document.getElementById('settingsModal');
        if (e.target === modal) {
            closeSettingsModal();
        }
    });
    


});

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
