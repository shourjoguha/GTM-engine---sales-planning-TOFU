/* ── GTM Planning Engine - Loading Overlay Module ── */

(function() {
  'use strict';

  /**
   * Loading Overlay state
   */
  const LOADING_STATE = {
    is_visible: false,
    progress: 0,
    status_message: '',
    simulation_interval: null,
    simulation_speed: 100 // ms between progress updates
  };

  /**
   * Status messages based on progress
   */
  const STATUS_MESSAGES = {
    validating: 'Validating configuration...',
    generating: 'Generating plan...',
    optimizing: 'Running optimizer...',
    calculating: 'Calculating allocations...',
    reporting: 'Generating reports...',
    completing: 'Completing...'
  };

  /**
   * DOM element references
   */
  const DOM = {
    overlay: null,
    spinner_container: null,
    progress_container: null,
    progress_bar: null,
    progress_fill: null,
    progress_text: null,
    status_text: null
  };

  /**
   * Initialize the loading overlay
   */
  function initialize() {
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('LoadingOverlay', 'Initializing');
    }

    // Get DOM elements
    DOM.overlay = document.getElementById('loadingOverlay');
    if (!DOM.overlay) {
      console.error('Loading Overlay - Overlay element not found');
      return;
    }

    // Build overlay content structure
    build_overlay_structure();

    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('LoadingOverlay', 'Initialized successfully');
    }
  }

  /**
   * Build the overlay HTML structure
   */
  function build_overlay_structure() {
    const overlay_inner = document.createElement('div');
    overlay_inner.className = 'loading-overlay-inner';

    // Spinner container using shared SpinnerUtility
    DOM.spinner_container = document.createElement('div');
    DOM.spinner_container.className = 'loading-spinner-container';

    // Use shared spinner utility
    if (typeof SpinnerUtility !== 'undefined' && SpinnerUtility.create) {
      const spinner_element = SpinnerUtility.create('default');
      DOM.spinner_container.appendChild(spinner_element);
    } else {
      // Fallback if SpinnerUtility not available
      DOM.spinner_container.innerHTML = `
        <svg viewBox="0 0 50 50" class="spinner-svg">
          <circle class="spinner-bg" cx="25" cy="25" r="20" fill="none" stroke="#e5e7eb" stroke-width="4" />
          <circle class="spinner-path" cx="25" cy="25" r="20" fill="none" stroke="#4f46e5" stroke-width="4" stroke-linecap="round" stroke-dasharray="100" stroke-dashoffset="25" />
        </svg>
      `;
    }

    // Progress container
    DOM.progress_container = document.createElement('div');
    DOM.progress_container.className = 'loading-progress-container';

    // Progress bar wrapper
    const progress_bar_wrapper = document.createElement('div');
    progress_bar_wrapper.className = 'progress-bar-wrapper';

    // Progress bar
    DOM.progress_bar = document.createElement('div');
    DOM.progress_bar.className = 'progress-bar';
    DOM.progress_bar.setAttribute('role', 'progressbar');
    DOM.progress_bar.setAttribute('aria-valuenow', '0');
    DOM.progress_bar.setAttribute('aria-valuemin', '0');
    DOM.progress_bar.setAttribute('aria-valuemax', '100');

    // Progress fill
    DOM.progress_fill = document.createElement('div');
    DOM.progress_fill.className = 'progress-fill';

    // Progress text
    DOM.progress_text = document.createElement('div');
    DOM.progress_text.className = 'progress-text';
    DOM.progress_text.textContent = '0%';

    // Status text
    DOM.status_text = document.createElement('div');
    DOM.status_text.className = 'status-text';
    DOM.status_text.textContent = 'Initializing...';

    // Assemble progress bar
    DOM.progress_bar.appendChild(DOM.progress_fill);
    progress_bar_wrapper.appendChild(DOM.progress_bar);

    // Assemble progress container
    DOM.progress_container.appendChild(progress_bar_wrapper);
    DOM.progress_container.appendChild(DOM.progress_text);
    DOM.progress_container.appendChild(DOM.status_text);

    // Assemble overlay
    overlay_inner.appendChild(DOM.spinner_container);
    overlay_inner.appendChild(DOM.progress_container);

    // Clear existing content and add new structure
    DOM.overlay.innerHTML = '';
    DOM.overlay.appendChild(overlay_inner);
  }

  /**
   * Show the loading overlay
   * @param {Object} options - Configuration options
   * @param {string} options.status - Initial status message
   * @param {boolean} options.simulate_progress - Whether to simulate progress
   * @param {number} options.simulation_speed - Speed of progress simulation (ms)
   */
  function show(options = {}) {
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('LoadingOverlay', 'Showing');
    }

    const {
      status = 'Initializing...',
      simulate_progress = true,
      simulation_speed = 100
    } = options;

    // Update state
    LOADING_STATE.is_visible = true;
    LOADING_STATE.progress = 0;
    LOADING_STATE.status_message = status;
    LOADING_STATE.simulation_speed = simulation_speed;

    // Update UI
    DOM.overlay.classList.remove('hidden');
    update_progress(0);
    update_status(status);

    // Start progress simulation if enabled
    if (simulate_progress) {
      start_progress_simulation();
    }
  }

  /**
   * Hide the loading overlay
   */
  function hide() {
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('LoadingOverlay', 'Hiding');
    }

    // Stop progress simulation
    stop_progress_simulation();

    // Update state
    LOADING_STATE.is_visible = false;

    // Hide overlay with animation
    DOM.overlay.classList.add('hidden');

    // Reset progress after animation
    setTimeout(() => {
      LOADING_STATE.progress = 0;
      update_progress(0);
    }, 300);
  }

  /**
   * Update progress bar
   * @param {number} progress - Progress value (0-100)
   */
  function update_progress(progress) {
    // Clamp progress to 0-100
    progress = Math.max(0, Math.min(100, progress));

    // Update state
    LOADING_STATE.progress = progress;

    // Update UI
    if (DOM.progress_fill) {
      DOM.progress_fill.style.width = `${progress}%`;
    }

    if (DOM.progress_text) {
      DOM.progress_text.textContent = `${Math.round(progress)}%`;
    }

    if (DOM.progress_bar) {
      DOM.progress_bar.setAttribute('aria-valuenow', Math.round(progress));
    }

    // Update status based on progress
    update_status_from_progress(progress);
  }

  /**
   * Update status message
   * @param {string} message - Status message
   */
  function update_status(message) {
    LOADING_STATE.status_message = message;

    if (DOM.status_text) {
      DOM.status_text.textContent = message;
    }
  }

  /**
   * Update status message based on progress
   * @param {number} progress - Progress value (0-100)
   */
  function update_status_from_progress(progress) {
    let status_message;

    if (progress < 20) {
      status_message = STATUS_MESSAGES.validating;
    } else if (progress < 40) {
      status_message = STATUS_MESSAGES.generating;
    } else if (progress < 60) {
      status_message = STATUS_MESSAGES.optimizing;
    } else if (progress < 80) {
      status_message = STATUS_MESSAGES.calculating;
    } else if (progress < 90) {
      status_message = STATUS_MESSAGES.reporting;
    } else {
      status_message = STATUS_MESSAGES.completing;
    }

    update_status(status_message);
  }

  /**
   * Start progress simulation
   */
  function start_progress_simulation() {
    stop_progress_simulation();

    LOADING_STATE.simulation_interval = setInterval(() => {
      const current_progress = LOADING_STATE.progress;

      // Simulate non-linear progress with varying speeds
      let increment;

      if (current_progress < 20) {
        // Fast initial progress
        increment = Math.random() * 2 + 1;
      } else if (current_progress < 40) {
        // Slower progress during generation
        increment = Math.random() * 1.5 + 0.5;
      } else if (current_progress < 60) {
        // Slow progress during optimization
        increment = Math.random() * 1 + 0.3;
      } else if (current_progress < 80) {
        // Moderate progress during calculation
        increment = Math.random() * 1.2 + 0.5;
      } else if (current_progress < 90) {
        // Fast progress during reporting
        increment = Math.random() * 2 + 1;
      } else {
        // Slow down near completion
        increment = Math.random() * 0.5 + 0.2;
      }

      const new_progress = Math.min(current_progress + increment, 95); // Cap at 95% until completion
      update_progress(new_progress);

    }, LOADING_STATE.simulation_speed);
  }

  /**
   * Stop progress simulation
   */
  function stop_progress_simulation() {
    if (LOADING_STATE.simulation_interval) {
      clearInterval(LOADING_STATE.simulation_interval);
      LOADING_STATE.simulation_interval = null;
    }
  }

  /**
   * Complete the loading process
   * @param {Function} callback - Optional callback after completion
   */
  function complete(callback) {
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('LoadingOverlay', 'Completing');
    }

    // Stop simulation
    stop_progress_simulation();

    // Jump to 100%
    update_progress(100);
    update_status('Complete!');

    // Hide overlay after brief delay
    setTimeout(() => {
      hide();

      // Execute callback if provided
      if (typeof callback === 'function') {
        callback();
      }
    }, 500);
  }

  /**
   * Get current loading state
   * @returns {Object} Current loading state
   */
  function get_state() {
    return {
      is_visible: LOADING_STATE.is_visible,
      progress: LOADING_STATE.progress,
      status_message: LOADING_STATE.status_message
    };
  }

  /**
   * Public API for the Loading Overlay
   */
  window.LoadingOverlay = {
    initialize: initialize,
    show: show,
    hide: hide,
    update_progress: update_progress,
    update_status: update_status,
    complete: complete,
    get_state: get_state
  };

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize);
  } else {
    initialize();
  }

})();
