/* ── GTM Planning Engine - Application Bootstrap ── */

(function() {
  'use strict';

  /**
   * Application state and configuration
   */
  const APP_STATE = {
    is_loaded: false,
    current_tab: 'config',
    api_base: '/api'
  };

  /**
   * DOM element references
   */
  const DOM = {
    loading_overlay: null,
    docs_button: null
  };

  /**
   * Initialize the application
   */
  function initialize() {
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('GTMApp', 'Initializing...');
    }

    // Get DOM elements
    DOM.loading_overlay = document.getElementById('loadingOverlay');
    DOM.docs_button = document.getElementById('docsBtn');

    // Setup event listeners
    setup_event_listeners();

    // Initialize loading overlay
    if (typeof LoadingOverlay !== 'undefined') {
      LoadingOverlay.initialize();
    }

    // Initialize tab manager
    if (typeof TabManager !== 'undefined') {
      TabManager.initialize();
    }

    // Initialize config form
    if (typeof ConfigForm !== 'undefined') {
      ConfigForm.initialize();
    }

    // Hide loading overlay after initialization
    hide_loading_overlay();
    APP_STATE.is_loaded = true;
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('GTMApp', 'Initialized successfully');
    }
  }

  /**
   * Setup global event listeners
   */
  function setup_event_listeners() {
    // Docs button click handler
    if (DOM.docs_button) {
      DOM.docs_button.addEventListener('click', handle_docs_click);
    }

    // Handle browser back/forward navigation
    window.addEventListener('popstate', handle_navigation);

    // Handle hash changes
    window.addEventListener('hashchange', handle_hash_change);
  }

  /**
   * Handle docs button click
   */
  function handle_docs_click(event) {
    event.preventDefault();
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('GTMApp', 'Docs button clicked - Documentation feature coming soon');
    }
  }

  /**
   * Handle browser navigation (back/forward buttons)
   */
  function handle_navigation(event) {
    const hash = window.location.hash || '#config';
    const tab_name = hash.substring(1);

    if (typeof TabManager !== 'undefined') {
      TabManager.switch_tab(tab_name);
    }
  }

  /**
   * Handle hash changes in URL
   */
  function handle_hash_change() {
    const hash = window.location.hash || '#config';
    const tab_name = hash.substring(1);

    if (typeof TabManager !== 'undefined') {
      TabManager.switch_tab(tab_name);
    }
  }

  /**
   * Show loading overlay
   */
  function show_loading_overlay(options = {}) {
    if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.show) {
      LoadingOverlay.show(options);
    } else if (DOM.loading_overlay) {
      DOM.loading_overlay.classList.remove('hidden');
    }
  }

  /**
   * Hide loading overlay
   */
  function hide_loading_overlay() {
    if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.hide) {
      LoadingOverlay.hide();
    } else if (DOM.loading_overlay) {
      DOM.loading_overlay.classList.add('hidden');
    }
  }

  /**
   * Complete loading overlay
   */
  function complete_loading_overlay(callback) {
    if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.complete) {
      LoadingOverlay.complete(callback);
    } else {
      hide_loading_overlay();
      if (typeof callback === 'function') {
        callback();
      }
    }
  }

  /**
   * Global API for other modules
   */
  window.GTMApp = {
    state: APP_STATE,
    dom: DOM,
    show_loading: show_loading_overlay,
    hide_loading: hide_loading_overlay,
    complete_loading: complete_loading_overlay,
    is_loaded: () => APP_STATE.is_loaded
  };

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }

})();
