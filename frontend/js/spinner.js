/* ── GTM Planning Engine - Spinner Utility ── */

(function() {
  'use strict';

  /**
   * Spinner templates for different sizes/types
   */
  const SPINNER_TEMPLATES = {
    default: `<svg viewBox="0 0 50 50" class="spinner-svg">
      <circle class="spinner-bg" cx="25" cy="25" r="20" fill="none" stroke="#e5e7eb" stroke-width="4" />
      <circle class="spinner-path" cx="25" cy="25" r="20" fill="none" stroke="#4f46e5" stroke-width="4" stroke-linecap="round" stroke-dasharray="100" stroke-dashoffset="25" />
    </svg>`,
    
    small: `<svg viewBox="0 0 24 24" class="spinner-svg spinner-small">
      <circle class="spinner-bg" cx="12" cy="12" r="10" fill="none" stroke="#e5e7eb" stroke-width="2" />
      <circle class="spinner-path" cx="12" cy="12" r="10" fill="none" stroke="#4f46e5" stroke-width="2" stroke-linecap="round" stroke-dasharray="100" stroke-dashoffset="25" />
    </svg>`
  };

  /**
   * Get spinner template as HTML string
   * @param {string} type - Spinner type ('default' or 'small')
   * @returns {string} SVG HTML string
   */
  function get_spinner(type = 'default') {
    return SPINNER_TEMPLATES[type] || SPINNER_TEMPLATES.default;
  }

  /**
   * Create spinner DOM element
   * @param {string} type - Spinner type ('default' or 'small')
   * @param {string} className - Additional CSS classes
   * @returns {HTMLElement} Spinner container element
   */
  function create_spinner_element(type = 'default', className = '') {
    const container = document.createElement('div');
    container.className = `loading-spinner ${className}`;
    container.innerHTML = get_spinner(type);
    return container;
  }

  /**
   * Public API for Spinner Utility
   */
  window.SpinnerUtility = {
    get: get_spinner,
    create: create_spinner_element
  };

})();
