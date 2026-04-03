/* ── GTM Planning Engine - Tab Manager ── */

(function() {
  'use strict';

  /**
   * Tab Manager state
   */
  const TAB_STATE = {
    current_tab: 'config',
    tabs: ['config', 'charts'],
    tab_panels: {},
    tab_buttons: {}
  };

  /**
   * DOM element references
   */
  const DOM = {
    tab_bar: null,
    tab_buttons: {},
    tab_panels: {}
  };

  /**
   * Initialize tab manager
   */
  function initialize() {
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('TabManager', 'Initializing');
    }

    // Cache DOM elements
    DOM.tab_bar = document.getElementById('tabBar');

    if (!DOM.tab_bar) {
      console.error('Tab Manager - Tab bar not found');
      return;
    }

    // Get all tab buttons
    const buttons = DOM.tab_bar.querySelectorAll('.tab-btn');
    buttons.forEach(button => {
      const tab_name = button.getAttribute('data-tab');
      if (tab_name) {
        DOM.tab_buttons[tab_name] = button;
      }
    });

    // Get all tab panels
    TAB_STATE.tabs.forEach(tab_name => {
      const panel = document.getElementById(`${tab_name}Panel`);
      if (panel) {
        DOM.tab_panels[tab_name] = panel;
        TAB_STATE.tab_panels[tab_name] = panel;
      }
    });

    // Setup event listeners
    setup_event_listeners();

    // Set initial tab from URL hash
    const initial_tab = get_initial_tab();
    if (initial_tab) {
      switch_tab(initial_tab);
    }

    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('TabManager', 'Initialized successfully');
    }
  }

  /**
   * Get initial tab from URL hash
   * @returns {string|null} Initial tab name or null
   */
  function get_initial_tab() {
    const hash = window.location.hash;
    if (hash && hash.startsWith('#')) {
      const initial_tab = hash.substring(1);
      if (TAB_STATE.tabs.includes(initial_tab)) {
        return initial_tab;
      }
    }
    return TAB_STATE.current_tab;
  }

  /**
   * Setup event listeners for tab buttons with keyboard navigation
   */
  function setup_event_listeners() {
    Object.keys(DOM.tab_buttons).forEach(tab_name => {
      const button = DOM.tab_buttons[tab_name];
      if (button) {
        // Click handler
        button.addEventListener('click', () => {
          switch_tab(tab_name);
        });

        // Keyboard navigation handler
        button.addEventListener('keydown', (event) => {
          handle_keyboard_navigation(event, tab_name);
        });
      }
    });
  }

  /**
   * Handle keyboard navigation for tabs
   * @param {KeyboardEvent} event - The keyboard event
   * @param {string} current_tab - The currently focused tab
   */
  function handle_keyboard_navigation(event, current_tab) {
    const tabs = TAB_STATE.tabs;
    const current_index = tabs.indexOf(current_tab);

    switch (event.key) {
      case 'ArrowLeft':
      case 'ArrowUp':
        event.preventDefault();
        const prev_index = (current_index - 1 + tabs.length) % tabs.length;
        switch_tab(tabs[prev_index]);
        DOM.tab_buttons[tabs[prev_index]]?.focus();
        break;

      case 'ArrowRight':
      case 'ArrowDown':
        event.preventDefault();
        const next_index = (current_index + 1) % tabs.length;
        switch_tab(tabs[next_index]);
        DOM.tab_buttons[tabs[next_index]]?.focus();
        break;

      case 'Home':
        event.preventDefault();
        switch_tab(tabs[0]);
        DOM.tab_buttons[tabs[0]]?.focus();
        break;

      case 'End':
        event.preventDefault();
        switch_tab(tabs[tabs.length - 1]);
        DOM.tab_buttons[tabs[tabs.length - 1]]?.focus();
        break;
    }
  }

  /**
   * Switch to a specific tab with accessibility updates
   * @param {string} tab_name - The name of tab to switch to
   */
  function switch_tab(tab_name) {
    if (!TAB_STATE.tabs.includes(tab_name)) {
      console.error(`Tab Manager - Invalid tab name: ${tab_name}`);
      return;
    }

    // If already on this tab, do nothing
    if (TAB_STATE.current_tab === tab_name) {
      return;
    }

    // Update active tab state
    TAB_STATE.current_tab = tab_name;

    // Update URL hash without triggering hashchange event
    const new_hash = `#${tab_name}`;
    if (window.location.hash !== new_hash) {
      history.pushState(null, null, new_hash);
    }

    // Update tab button states with ARIA attributes
    update_tab_buttons(tab_name);

    // Update tab panel visibility
    update_tab_panels(tab_name);

    // Dispatch custom event for other modules
    dispatch_tab_change_event(tab_name);

    if (window.APIClient?.debug_log) {
      window.APIClient.debug_log('Tab Manager', `Switched to tab: ${tab_name}`);
    }
  }

  /**
   * Update tab button active states with ARIA attributes
   * @param {string} active_tab_name - The name of the active tab
   */
  function update_tab_buttons(active_tab_name) {
    Object.keys(DOM.tab_buttons).forEach(tab_name => {
      const button = DOM.tab_buttons[tab_name];
      if (button) {
        const is_active = tab_name === active_tab_name;

        if (is_active) {
          button.classList.add('active');
          button.setAttribute('aria-selected', 'true');
          button.setAttribute('tabindex', '0');
        } else {
          button.classList.remove('active');
          button.setAttribute('aria-selected', 'false');
          button.setAttribute('tabindex', '-1');
        }
      }
    });
  }

  /**
   * Update tab panel visibility with ARIA attributes
   * @param {string} active_tab_name - The name of the active tab
   */
  function update_tab_panels(active_tab_name) {
    Object.keys(DOM.tab_panels).forEach(tab_name => {
      const panel = DOM.tab_panels[tab_name];
      if (panel) {
        const is_active = tab_name === active_tab_name;

        if (is_active) {
          panel.classList.remove('hidden');
          panel.setAttribute('aria-hidden', 'false');
        } else {
          panel.classList.add('hidden');
          panel.setAttribute('aria-hidden', 'true');
        }
      }
    });
  }

  /**
   * Dispatch a custom event when tab changes
   * @param {string} tab_name - The name of the tab that was activated
   */
  function dispatch_tab_change_event(tab_name) {
    const event = new CustomEvent('tabchange', {
      detail: {
        tab: tab_name
      },
      bubbles: true
    });
    document.dispatchEvent(event);
  }

  /**
   * Get the current active tab
   * @returns {string} The name of the current active tab
   */
  function get_current_tab() {
    return TAB_STATE.current_tab;
  }

  /**
   * Check if a specific tab is active
   * @param {string} tab_name - The name of the tab to check
   * @returns {boolean} True if the tab is active, false otherwise
   */
  function is_tab_active(tab_name) {
    return TAB_STATE.current_tab === tab_name;
  }

  /**
   * Public API for the Tab Manager
   */
  window.TabManager = {
    initialize: initialize,
    switch_tab: switch_tab,
    get_current_tab: get_current_tab,
    is_tab_active: is_tab_active,
    tabs: TAB_STATE.tabs
  };

})();
