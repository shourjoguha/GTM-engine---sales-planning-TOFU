/* ── GTM Planning Engine - Charts Viewer ── */

(function() {
  'use strict';

  /**
   * Charts Viewer state
   */
  const CHART_VIEWER_STATE = {
    current_version: null,
    chart_server_url: null,
    versions: [],
    is_loading: false,
    is_fullscreen: false,
    latest_version_id: null,
    iframe_origin: null,
    loading_version: null,
    cache: {
      versions: null,
      versions_timestamp: 0
    },
    cache_duration: 300000 // 5 minutes cache
  };

  /**
   * DOM element references
   */
  const DOM = {
    charts_panel: null,
    version_selector: null,
    refresh_button: null,
    fullscreen_button: null,
    iframe_container: null,
    iframe: null,
    loading_indicator: null,
    error_message: null,
    empty_state: null
  };

  /**
   * Initialize the charts viewer
   */
  async function initialize() {
    if (window.APIClient?.debug_log) {
      window.APIClient.debug_log('Charts Viewer', 'Initializing');
    }

    // Get DOM elements
    DOM.charts_panel = document.getElementById('chartsPanel');
    if (!DOM.charts_panel) {
      console.error('Charts Viewer - Charts panel not found');
      return;
    }

    // Load versions list
    await load_versions();

    // Generate charts viewer UI
    generate_charts_viewer_ui();

    // Setup event listeners
    setup_event_listeners();

    // Listen for plan completion event
    setup_plan_completion_listener();

    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('ChartViewer', 'Initialized successfully');
    }
  }

  /**
   * Generate charts viewer UI
   */
  function generate_charts_viewer_ui() {
    const ui_html = `
      <div class="charts-viewer-container">
        <div class="charts-header">
          <div class="header-title-section">
            <h2 class="charts-title">Reports & Charts</h2>
            <p class="charts-subtitle">View your GTM planning analytics and visualizations</p>
          </div>
          <div class="header-controls">
            <div class="version-selector-wrapper">
              <label class="version-label" for="versionSelector">Version:</label>
              <select id="versionSelector" class="version-selector">
                <option value="">Loading versions...</option>
              </select>
            </div>
            <button id="refreshBtn" class="btn btn-secondary btn-icon" title="Refresh Charts">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M23 4v6h-6"/>
                <path d="M1 20v-6h6"/>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
              </svg>
              Refresh
            </button>
            <button id="fullscreenBtn" class="btn btn-secondary btn-icon" title="Toggle Fullscreen">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
              </svg>
              Fullscreen
            </button>
          </div>
        </div>

        <div class="charts-content">
          <div id="emptyState" class="empty-state">
            <div class="empty-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="20" x2="18" y2="10"/>
                <line x1="12" y1="20" x2="12" y2="4"/>
                <line x1="6" y1="20" x2="6" y2="14"/>
              </svg>
            </div>
            <h3>No Charts Available</h3>
            <p>Select a version to view charts or run a new plan to generate analytics.</p>
          </div>

          <div id="loadingIndicator" class="charts-loading hidden">
            <p>Loading charts...</p>
          </div>

          <div id="errorMessage" class="charts-error hidden">
            <div class="error-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
            </div>
            <h3>Error Loading Charts</h3>
            <p id="chartsErrorText">Failed to load charts. Please try again.</p>
            <button id="retryBtn" class="btn btn-primary">Retry</button>
          </div>

          <div id="iframeContainer" class="iframe-container hidden">
            <iframe id="chartsIframe" class="charts-iframe" title="Charts Viewer" allowfullscreen></iframe>
          </div>
        </div>
      </div>
    `;

    DOM.charts_panel.innerHTML = ui_html;

    // Get DOM element references
    DOM.version_selector = document.getElementById('versionSelector');
    DOM.refresh_button = document.getElementById('refreshBtn');
    DOM.fullscreen_button = document.getElementById('fullscreenBtn');
    DOM.iframe_container = document.getElementById('iframeContainer');
    DOM.iframe = document.getElementById('chartsIframe');
    DOM.loading_indicator = document.getElementById('loadingIndicator');
    DOM.error_message = document.getElementById('errorMessage');
    DOM.empty_state = document.getElementById('emptyState');
  }

  /**
   * Setup event listeners
   */
  function setup_event_listeners() {
    // Version selector change
    if (DOM.version_selector) {
      DOM.version_selector.addEventListener('change', handle_version_change);
    }

    // Refresh button
    if (DOM.refresh_button) {
      DOM.refresh_button.addEventListener('click', handle_refresh);
    }

    // Fullscreen button
    if (DOM.fullscreen_button) {
      DOM.fullscreen_button.addEventListener('click', handle_fullscreen);
    }

    // Retry button
    const retryBtn = document.getElementById('retryBtn');
    if (retryBtn) {
      retryBtn.addEventListener('click', handle_refresh);
    }

    // Iframe load events
    if (DOM.iframe) {
      DOM.iframe.addEventListener('load', handle_iframe_load);
      DOM.iframe.addEventListener('error', handle_iframe_error);
    }

    // Listen for tab changes to load charts when switching to charts tab
    document.addEventListener('tabchange', handle_tab_change);
    window.addEventListener('message', handle_iframe_message);
  }

  /**
   * Setup plan completion listener with automatic version list refresh
   */
  function setup_plan_completion_listener() {
    document.addEventListener('plancomplete', async (event) => {
      const version_id = event.detail.version_id;
      const chart_server_url = event.detail.chart_server_url;

      if (window.APIClient?.debug_log) {
        window.APIClient.debug_log('Charts Viewer', 'Plan completed', version_id);
      }

      // Update state with new version
      if (version_id) {
        CHART_VIEWER_STATE.current_version = version_id;
        CHART_VIEWER_STATE.chart_server_url = chart_server_url;
      }

      // Force refresh versions list to include new version
      await load_versions(true);

      // Select new version after versions are loaded
      if (version_id && DOM.version_selector) {
        DOM.version_selector.value = version_id;
        const charts_tab = document.getElementById('charts-tab');
        const is_charts_active = !!charts_tab?.classList.contains('active');
        if (is_charts_active) {
          load_charts_for_version(version_id);
        }
      }
    });
  }

  /**
   * Load versions list from API with caching and improved error handling
   */
  async function load_versions(force_refresh = false) {
    const now = Date.now();
    const cache_age = now - CHART_VIEWER_STATE.cache.versions_timestamp;

    // Return cached versions if available and not expired
    if (!force_refresh && CHART_VIEWER_STATE.cache.versions && cache_age < CHART_VIEWER_STATE.cache_duration) {
      CHART_VIEWER_STATE.versions = CHART_VIEWER_STATE.cache.versions;
      update_version_selector();
      if (window.APIClient?.debug_log) {
        window.APIClient.debug_log('Charts Viewer', 'Using cached versions');
      }
      return;
    }

    try {
      const response = await fetch('/api/versions');
      if (!response.ok) {
        throw new Error(`Server responded with HTTP ${response.status}`);
      }

      const data = await response.json();
      CHART_VIEWER_STATE.versions = data.versions || [];

      // Sort by created timestamp descending
      if (CHART_VIEWER_STATE.versions.length > 0) {
        CHART_VIEWER_STATE.versions.sort((a, b) => b.created - a.created);
        CHART_VIEWER_STATE.latest_version_id = CHART_VIEWER_STATE.versions[0].id;
      }

      // Update cache
      CHART_VIEWER_STATE.cache.versions = [...CHART_VIEWER_STATE.versions];
      CHART_VIEWER_STATE.cache.versions_timestamp = now;

      // Update version selector
      update_version_selector();

      if (window.APIClient?.debug_log) {
        window.APIClient.debug_log('Charts Viewer', 'Versions loaded', CHART_VIEWER_STATE.versions.length);
      }
    } catch (error) {
      console.error('Charts Viewer - Failed to load versions:', error);
      CHART_VIEWER_STATE.versions = [];
      update_version_selector();
      show_versions_error(error.message);
    }
  }

  /**
   * Show versions loading error
   * @param {string} error_message - The error message
   */
  function show_versions_error(error_message) {
    if (DOM.version_selector) {
      DOM.version_selector.innerHTML = `
        <option value="">Error loading versions</option>
      `;
      DOM.version_selector.disabled = true;
    }

    show_error(
      `Unable to load plan versions. ${error_message}\n\nPlease check your connection and try again.`
    );
  }

  /**
   * Update version selector dropdown
   */
  function update_version_selector() {
    if (!DOM.version_selector) return;

    if (CHART_VIEWER_STATE.versions.length === 0) {
      DOM.version_selector.innerHTML = '<option value="">No versions available</option>';
      DOM.version_selector.disabled = true;
      return;
    }

    // Generate options
    const options = CHART_VIEWER_STATE.versions.map(version => {
      const date = new Date(version.created * 1000);
      const date_str = date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });

      return `<option value="${version.id}">${version.id} - ${date_str}</option>`;
    }).join('');

    DOM.version_selector.innerHTML = options;
    DOM.version_selector.disabled = false;

    // Auto-select latest version if not already selected
    if (!CHART_VIEWER_STATE.current_version && CHART_VIEWER_STATE.latest_version_id) {
      DOM.version_selector.value = CHART_VIEWER_STATE.latest_version_id;
      CHART_VIEWER_STATE.current_version = CHART_VIEWER_STATE.latest_version_id;
    }
  }

  /**
   * Handle version selector change
   */
  function handle_version_change(event) {
    const version_id = event.target.value;

    if (window.APIClient?.debug_log) {
      window.APIClient.debug_log('Charts Viewer', 'Version changed to', version_id);
    }

    if (!version_id) {
      show_empty_state();
      return;
    }

    CHART_VIEWER_STATE.current_version = version_id;
    CHART_VIEWER_STATE.chart_server_url = null;

    load_charts_for_version(version_id);
  }

  /**
   * Load charts for a specific version
   */
  async function load_charts_for_version(version_id) {
    if (!version_id) {
      show_empty_state();
      return;
    }
    if (CHART_VIEWER_STATE.loading_version === version_id) {
      return;
    }
    if (CHART_VIEWER_STATE.current_version === version_id && CHART_VIEWER_STATE.chart_server_url && DOM.iframe?.src === CHART_VIEWER_STATE.chart_server_url) {
      hide_loading();
      return;
    }

    if (window.APIClient?.debug_log) {
      window.APIClient.debug_log('Charts Viewer', 'Loading charts for version', version_id);
    }

    // Show loading indicator
    show_loading();
    CHART_VIEWER_STATE.loading_version = version_id;

    try {
      // Check if chart server is already running
      const status_response = await fetch(`/api/charts/server/${version_id}/status`);
      const status_data = await status_response.json();

      let chart_url = null;

      if (status_data.status === 'running') {
        // Server already running
        chart_url = status_data.url;
        if (window.APIClient?.debug_log) {
          window.APIClient.debug_log('Charts Viewer', 'Chart server already running', chart_url);
        }
      } else {
        // Start chart server
        if (window.APIClient?.debug_log) {
          window.APIClient.debug_log('Charts Viewer', 'Starting chart server for version', version_id);
        }
        const start_response = await fetch(`/api/charts/server/${version_id}`, {
          method: 'POST'
        });

        if (!start_response.ok) {
          throw new Error(`Failed to start chart server: HTTP ${start_response.status}`);
        }

        const start_data = await start_response.json();
        chart_url = start_data.url;
        if (window.APIClient?.debug_log) {
          window.APIClient.debug_log('Charts Viewer', 'Chart server started', chart_url);
        }
      }

      // Update state
      CHART_VIEWER_STATE.chart_server_url = chart_url;
      try {
        CHART_VIEWER_STATE.iframe_origin = new URL(chart_url).origin;
      } catch (error) {
        CHART_VIEWER_STATE.iframe_origin = null;
      }

      // Load charts in iframe
      load_iframe(chart_url);

    } catch (error) {
      console.error('Charts Viewer - Failed to load charts:', error);
      show_error(error.message);
    } finally {
      CHART_VIEWER_STATE.loading_version = null;
    }
  }

  /**
   * Load URL in iframe
   */
  function load_iframe(url) {
    if (!DOM.iframe) return;

    if (window.APIClient?.debug_log) {
      window.APIClient.debug_log('Charts Viewer', 'Loading iframe URL', url);
    }

    // Set iframe source
    DOM.iframe.src = url;
    DOM.iframe_container.style.height = '';

    // Show iframe container
    hide_all_states();
    DOM.iframe_container.classList.remove('hidden');
  }

  /**
   * Handle iframe load event
   */
  function handle_iframe_load() {
    if (window.APIClient?.debug_log) {
      window.APIClient.debug_log('Charts Viewer', 'Iframe loaded successfully');
    }
    hide_loading();
  }

  /**
   * Handle iframe error event
   */
  function handle_iframe_error() {
    console.error('Charts Viewer - Iframe error');
    show_error('Failed to load charts. The chart server may be unavailable.');
  }

  function handle_iframe_message(event) {
    if (!DOM.iframe_container || !event?.data || event.data.type !== 'charts-content-height') {
      return;
    }
    if (CHART_VIEWER_STATE.iframe_origin && event.origin !== CHART_VIEWER_STATE.iframe_origin) {
      return;
    }
    const next_height = parseInt(event.data.height, 10);
    if (!Number.isFinite(next_height) || next_height <= 0) {
      return;
    }
    const bounded_height = Math.max(520, Math.min(next_height + 12, 2200));
    DOM.iframe_container.style.height = `${bounded_height}px`;
  }

  /**
   * Handle refresh button click
   */
  function handle_refresh() {
    if (!CHART_VIEWER_STATE.current_version) {
      show_empty_state();
      return;
    }

    if (window.APIClient?.debug_log) {
      window.APIClient.debug_log('Charts Viewer', 'Refreshing charts');
    }
    load_charts_for_version(CHART_VIEWER_STATE.current_version);
  }

  /**
   * Handle fullscreen toggle
   */
  function handle_fullscreen() {
    if (!DOM.iframe_container) return;

    if (!CHART_VIEWER_STATE.is_fullscreen) {
      // Enter fullscreen
      if (DOM.iframe_container.requestFullscreen) {
        DOM.iframe_container.requestFullscreen();
      } else if (DOM.iframe_container.webkitRequestFullscreen) {
        DOM.iframe_container.webkitRequestFullscreen();
      } else if (DOM.iframe_container.msRequestFullscreen) {
        DOM.iframe_container.msRequestFullscreen();
      }
      CHART_VIEWER_STATE.is_fullscreen = true;
    } else {
      // Exit fullscreen
      if (document.exitFullscreen) {
        document.exitFullscreen();
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      } else if (document.msExitFullscreen) {
        document.msExitFullscreen();
      }
      CHART_VIEWER_STATE.is_fullscreen = false;
    }
  }

  /**
   * Handle tab change event
   */
  function handle_tab_change(event) {
    const tab_name = event.detail.tab;

    if (tab_name === 'charts' && CHART_VIEWER_STATE.current_version && !CHART_VIEWER_STATE.chart_server_url) {
      // Auto-load charts when switching to charts tab
      if (window.APIClient?.debug_log) {
        window.APIClient.debug_log('Charts Viewer', 'Switched to charts tab, loading charts');
      }
      load_charts_for_version(CHART_VIEWER_STATE.current_version);
    }
  }

  /**
   * Show loading indicator
   */
  function show_loading() {
    hide_all_states();
    if (DOM.loading_indicator) {
      DOM.loading_indicator.classList.remove('hidden');
      
      // Add spinner if not present
      if (!DOM.loading_indicator.querySelector('.loading-spinner') && typeof SpinnerUtility !== 'undefined' && SpinnerUtility.create) {
        const spinner = SpinnerUtility.create('default');
        DOM.loading_indicator.insertBefore(spinner, DOM.loading_indicator.firstChild);
      }
    }
    CHART_VIEWER_STATE.is_loading = true;
  }

  /**
   * Hide loading indicator
   */
  function hide_loading() {
    if (DOM.loading_indicator) {
      DOM.loading_indicator.classList.add('hidden');
    }
    CHART_VIEWER_STATE.is_loading = false;
  }

  /**
   * Show error message
   */
  function show_error(message) {
    hide_all_states();
    if (DOM.error_message) {
      const error_text = document.getElementById('chartsErrorText');
      if (error_text) {
        error_text.textContent = message;
      }
      DOM.error_message.classList.remove('hidden');
    }
  }

  /**
   * Show empty state
   */
  function show_empty_state() {
    hide_all_states();
    if (DOM.empty_state) {
      DOM.empty_state.classList.remove('hidden');
    }
  }

  /**
   * Hide all states
   */
  function hide_all_states() {
    if (DOM.loading_indicator) {
      DOM.loading_indicator.classList.add('hidden');
    }
    if (DOM.error_message) {
      DOM.error_message.classList.add('hidden');
    }
    if (DOM.empty_state) {
      DOM.empty_state.classList.add('hidden');
    }
    if (DOM.iframe_container) {
      DOM.iframe_container.classList.add('hidden');
    }
  }

  /**
   * Public API for the Charts Viewer
   */
  window.ChartViewer = {
    initialize: initialize,
    load_charts: load_charts_for_version,
    refresh: handle_refresh,
    get_current_version: () => CHART_VIEWER_STATE.current_version
  };

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }

})();
