/* ========================================
INITIALISATION
======================================== */

// Initialisation au chargement de la page
document.addEventListener(‘DOMContentLoaded’, function() {
initDarkMode();
initModalEventListeners();
});

/* ========================================
DARK MODE
======================================== */

/**

- Initialiser le dark mode depuis localStorage
  */
  function initDarkMode() {
  const isDarkMode = localStorage.getItem(‘darkMode’) === ‘true’;
  const toggle = document.getElementById(‘darkModeToggle’);
  
  if (isDarkMode) {
  document.documentElement.setAttribute(‘data-theme’, ‘dark’);
  if (toggle) {
  toggle.checked = true;
  }
  }
  }

/**

- Basculer le dark mode
  */
  function toggleDarkMode() {
  const toggle = document.getElementById(‘darkModeToggle’);
  const isDarkMode = toggle.checked;
  
  if (isDarkMode) {
  document.documentElement.setAttribute(‘data-theme’, ‘dark’);
  localStorage.setItem(‘darkMode’, ‘true’);
  } else {
  document.documentElement.removeAttribute(‘data-theme’);
  localStorage.setItem(‘darkMode’, ‘false’);
  }
  }

/* ========================================
MODAL CONTROLS
======================================== */

/**

- Ouvrir le modal
  */
  function openModal() {
  const modal = document.getElementById(‘permissionModal’);
  const backdrop = document.getElementById(‘modalBackdrop’);
  
  if (modal && backdrop) {
  modal.classList.add(‘show’);
  backdrop.classList.add(‘show’);
  }
  }

/**

- Fermer le modal
  */
  function closeModal() {
  const modal = document.getElementById(‘permissionModal’);
  const backdrop = document.getElementById(‘modalBackdrop’);
  
  if (modal && backdrop) {
  modal.classList.remove(‘show’);
  backdrop.classList.remove(‘show’);
  }
  }

/* ========================================
EVENT LISTENERS
======================================== */

/**

- Initialiser les event listeners pour le modal
  */
  function initModalEventListeners() {
  // Fermer le modal en cliquant sur le backdrop
  const backdrop = document.getElementById(‘modalBackdrop’);
  if (backdrop) {
  backdrop.addEventListener(‘click’, function() {
  closeModal();
  });
  }
  
  // Fermer le modal avec la touche Escape
  document.addEventListener(‘keydown’, function(event) {
  if (event.key === ‘Escape’) {
  const modal = document.getElementById(‘permissionModal’);
  if (modal && modal.classList.contains(‘show’)) {
  closeModal();
  }
  }
  });
  }
