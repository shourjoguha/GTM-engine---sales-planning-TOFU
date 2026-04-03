/* ── GTM Planning Engine - Configuration Form ── */

(function() {
  'use strict';

  /**
   * Configuration Form state
   */
  const FORM_STATE = {
    config_schema: null,
    is_loaded: false,
    is_initializing: false
  };

  /**
   * Tooltip content for form fields
   */
  const TOOLTIPS = {
    dimensions: {
      title: "Planning Dimensions",
      description: "Define which data dimensions are active for this planning run.",
      impact: "Disabled dimensions aggregate across all values.",
      example: "Enable region when regional data is available."
    },
    annual_target: {
      title: "Annual Target",
      description: "Total bookings target for the fiscal year.",
      impact: "Drives all allocation calculations and SAO targets.",
      example: "188000000 for $188M target."
    },
    growth_rate: {
      title: "Growth Rate",
      description: "Year-over-year growth percentage for target derivation.",
      impact: "Used to calculate targets from prior year actuals.",
      example: "0.50 for 50% growth."
    },
    target_source: {
      title: "Target Source",
      description: "How the annual target is determined.",
      impact: "Fixed uses explicit value, growth derives from prior year.",
      example: "Use 'growth' for annual planning."
    },
    seasonality_weights: {
      title: "Seasonality Weights",
      description: "Distribution of annual target across months.",
      impact: "Must sum to 1.0. Influences monthly SAO targets.",
      example: "Higher weights in peak months."
    },
    planning_mode: {
      title: "Planning Mode",
      description: "How the planning horizon is handled.",
      impact: "Full year plans all months, rolling forward locks completed months.",
      example: "Use 'rolling_forward' mid-year."
    },
    objective_metric: {
      title: "Objective Metric",
      description: "What the optimizer tries to maximize.",
      impact: "Changes optimization focus and results.",
      example: "Use 'bookings' for revenue focus."
    },
    share_floor: {
      title: "Share Floor",
      description: "Minimum share per segment.",
      impact: "Prevents segments from getting too small.",
      example: "0.03 for 3% minimum."
    },
    share_ceiling: {
      title: "Share Ceiling",
      description: "Maximum share per segment.",
      impact: "Prevents any segment from dominating.",
      example: "0.40 for 40% maximum."
    },
    optimizer_mode: {
      title: "Optimizer Mode",
      description: "Algorithm used for allocation optimization.",
      impact: "Solver is more precise, greedy is faster.",
      example: "Use 'solver' with cash cycle enabled."
    },
    use_calibration: {
      title: "Use Calibration",
      description: "Whether to use calibrated values from deal data.",
      impact: "Calibrated values more accurate when available.",
      example: "Set true when deal data exists."
    },
    asp_decay_function: {
      title: "ASP Decay Function",
      description: "How ASP decreases with volume.",
      impact: "Exponential for diminishing returns, linear for steady decline.",
      example: "Marketing channels often use step function."
    },
    asp_decay_rate: {
      title: "ASP Decay Rate",
      description: "Rate at which ASP decays.",
      impact: "Higher rate = faster decline with volume.",
      example: "0.001 for exponential decay."
    },
    asp_threshold: {
      title: "ASP Threshold",
      description: "Volume at which decay starts.",
      impact: "No decay until threshold reached.",
      example: "340 SAOs before decay starts."
    },
    asp_floor_multiplier: {
      title: "ASP Floor Multiplier",
      description: "Minimum ASP as fraction of baseline.",
      impact: "ASP won't drop below this level.",
      example: "0.75 for 75% of baseline."
    },
    win_rate_decay_function: {
      title: "Win Rate Decay Function",
      description: "How win rate decreases with volume.",
      impact: "Different channels have different decay patterns.",
      example: "Outbound often uses linear decay."
    },
    win_rate_decay_rate: {
      title: "Win Rate Decay Rate",
      description: "Rate at which win rate decays.",
      impact: "Higher rate = faster decline with volume.",
      example: "0.005 for slight linear decay."
    },
    win_rate_threshold: {
      title: "Win Rate Threshold",
      description: "Volume at which decay starts.",
      impact: "No decay until threshold reached.",
      example: "260 SAOs before decay starts."
    },
    win_rate_floor_multiplier: {
      title: "Win Rate Floor Multiplier",
      description: "Minimum win rate as fraction of baseline.",
      impact: "Win rate won't drop below this level.",
      example: "0.80 for 80% of baseline."
    },
    cash_cycle_enabled: {
      title: "Cash Cycle",
      description: "Model time lag between SAOs and bookings.",
      impact: "Accounts for deal close delays in planning.",
      example: "Enable when products have different cycles."
    },
    starting_hc: {
      title: "Starting Headcount",
      description: "Number of tenured AEs at fiscal year start.",
      impact: "Base capacity for the planning year.",
      example: "100 AEs starting FY26."
    },
    productivity_per_ae: {
      title: "Productivity per AE",
      description: "SAOs per fully-ramped AE per month.",
      impact: "Multiplied by effective AE capacity for targets.",
      example: "45 SAOs per AE per month."
    },
    ramp_duration_days: {
      title: "Ramp Duration",
      description: "Days to reach full productivity.",
      impact: "Affects effective capacity of new hires.",
      example: "45 days to full ramp."
    },
    mentoring_overhead: {
      title: "Mentoring Overhead",
      description: "Percentage of tenured AE time spent mentoring.",
      impact: "Reduces selling capacity of tenured AEs.",
      example: "0.05 for 5% overhead per new hire."
    },
    max_mentees_per_ae: {
      title: "Max Mentees per AE",
      description: "Maximum new hires a tenured AE mentors.",
      impact: "Limits mentoring tax on any single AE.",
      example: "3 mentees maximum per AE."
    },
    pto_pct: {
      title: "PTO Percentage",
      description: "Percentage of time on paid time off.",
      impact: "Reduces effective selling time.",
      example: "0.08 for ~4 weeks PTO annually."
    },
    admin_pct: {
      title: "Admin Percentage",
      description: "Percentage of time on administrative tasks.",
      impact: "Reduces effective selling time.",
      example: "0.05 for 5% admin time."
    },
    enablement_base_pct: {
      title: "Enablement Base",
      description: "Base percentage of time on training/enablement.",
      impact: "Minimum enablement time regardless of new hires.",
      example: "0.03 for 3% base enablement."
    },
    enablement_scaling: {
      title: "Enablement Scaling",
      description: "How enablement scales with new hires.",
      impact: "Proportional grows with hires, fixed stays at base.",
      example: "Use 'fixed' to cap enablement cost."
    },
    attrition_rate: {
      title: "Attrition Rate",
      description: "Annual percentage of AEs who leave.",
      impact: "Reduces capacity, requires backfill planning.",
      example: "0.10 for 10% annual attrition."
    },
    backfill_delay_months: {
      title: "Backfill Delay",
      description: "Months to backfill a departing AE.",
      impact: "Delay before replacement starts ramping.",
      example: "1 month to backfill."
    },
    stretch_threshold: {
      title: "Stretch Threshold",
      description: "Maximum quarterly capacity as multiple of plan.",
      impact: "Limits recovery rebalancing for underperformance.",
      example: "1.20 for 120% of original plan max."
    },
    output_dir: {
      title: "Output Directory",
      description: "Where version snapshots are saved.",
      impact: "Storage location for plan results.",
      example: "versions/ folder in project root."
    },
    solver_method: {
      title: "Solver Method",
      description: "Optimization algorithm for scipy mode.",
      impact: "Different methods have different tradeoffs.",
      example: "SLSQP is commonly used."
    },
    solver_max_iterations: {
      title: "Max Iterations",
      description: "Maximum solver iterations.",
      impact: "Higher iterations may find better solutions.",
      example: "1000 iterations maximum."
    },
    scenario_enabled: {
      title: "Scenario Enabled",
      description: "Toggle to activate this what-if scenario.",
      impact: "Scenario perturbations applied to base config.",
      example: "Enable to test risk scenarios."
    }
  };

  /**
   * DOM element references
   */
  const DOM = {
    config_panel: null,
    form_container: null,
    error_display: null,
    error_text: null,
    error_dismiss_btn: null
  };

  /**
   * Initialize the configuration form
   */
  async function initialize() {
    if (FORM_STATE.is_loaded || FORM_STATE.is_initializing) {
      return;
    }
    FORM_STATE.is_initializing = true;
    if (typeof Logger !== 'undefined' && Logger.debug) {
      Logger.debug('ConfigForm', 'Initializing...');
    }

    try {
      DOM.config_panel = document.getElementById('configPanel');
      if (!DOM.config_panel) {
        console.error('Config Form - Config panel not found');
        return;
      }

      DOM.error_display = document.getElementById('errorDisplay');
      DOM.error_text = document.getElementById('errorText');
      DOM.error_dismiss_btn = document.getElementById('errorDismissBtn');

      if (DOM.error_dismiss_btn) {
        DOM.error_dismiss_btn.addEventListener('click', hide_error);
      }

      await load_config_schema();
      generate_form();
      setup_event_listeners();

      FORM_STATE.is_loaded = true;
      if (typeof Logger !== 'undefined' && Logger.debug) {
        Logger.debug('ConfigForm', 'Initialized successfully');
      }
    } finally {
      FORM_STATE.is_initializing = false;
    }
  }

  /**
   * Show error display with message
   * @param {string} message - Error message to display
   */
  function show_error(message) {
    if (DOM.error_text) {
      DOM.error_text.textContent = message;
    }
    if (DOM.error_display) {
      DOM.error_display.classList.remove('hidden');
    }
  }

  /**
   * Hide error display
   */
  function hide_error() {
    if (DOM.error_display) {
      DOM.error_display.classList.add('hidden');
    }
  }

  /**
   * Load configuration schema from API
   */
  async function load_config_schema() {
    try {
      const response = await fetch('/api/config-schema');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      FORM_STATE.config_schema = await response.json();
      if (typeof Logger !== 'undefined' && Logger.debug) {
        Logger.debug('ConfigForm', 'Schema loaded successfully');
      }
    } catch (error) {
      console.error('Config Form - Failed to load schema:', error);
      FORM_STATE.config_schema = {};
      show_schema_error(error.message);
    }
  }

  /**
   * Show schema loading error with user-friendly message
   * @param {string} error_message - The error message
   */
  function show_schema_error(error_message) {
    if (DOM.config_panel) {
      DOM.config_panel.innerHTML = `
        <div class="panel-placeholder">
          <div class="placeholder-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
          </div>
          <h3>Unable to Load Configuration</h3>
          <p>We couldn't load the configuration schema. This might be a temporary issue.</p>
          <p class="error-detail">Error: ${error_message}</p>
          <button class="btn btn-primary" onclick="window.location.reload()">Try Again</button>
        </div>
      `;
    }
  }

  /**
   * Generate form from config schema
   */
  function generate_form() {
    if (!FORM_STATE.config_schema) {
      DOM.config_panel.innerHTML = `
        <div class="panel-placeholder">
          <div class="placeholder-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
            </svg>
          </div>
          <h3>Loading Configuration</h3>
          <p>Please wait while we load the configuration schema...</p>
        </div>
      `;
      return;
    }

    const form_html = `
      <div class="config-form-container">
        <div class="form-header">
          <h2>Plan Configuration</h2>
          <p>Configure your GTM planning parameters below</p>
        </div>

        <form id="configForm" class="config-form">
          ${generate_dimensions_section()}
          ${generate_targets_section()}
          ${generate_allocation_section()}
          ${generate_economics_section()}
          ${generate_ae_model_section()}
          ${generate_what_if_section()}
          ${generate_system_section()}

          <div class="form-actions">
            <button type="button" class="btn btn-secondary" id="resetBtn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
                <path d="M3 3v5h5"/>
              </svg>
              Reset to Defaults
            </button>
            <button type="submit" class="btn btn-primary" id="submitBtn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3"/>
              </svg>
              Run Plan
            </button>
          </div>
        </form>
      </div>
    `;

    DOM.config_panel.innerHTML = form_html;
    DOM.form_container = document.getElementById('configForm');
  }

  /**
   * Generate dimensions section
   */
  function generate_dimensions_section() {
    const config = FORM_STATE.config_schema;
    const dimensions = config.dimensions || {};

    return `
      <div class="form-section">
        <div class="section-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/>
              <rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/>
              <rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
            Dimensions
          </h3>
          ${generate_tooltip('dimensions')}
        </div>

        <div class="form-grid">
          ${Object.entries(dimensions).map(([key, value]) => `
            <div class="form-field">
              <div class="field-header">
                <label class="field-label">${format_label(key)}</label>
                <div class="field-controls">
                  <label class="toggle-switch">
                    <input type="checkbox" name="${key}_enabled" ${value.enabled ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                  </label>
                </div>
              </div>
              <div class="field-description">
                ${Array.isArray(value.values) ? value.values.join(', ') : ''}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  /**
   * Generate targets section
   */
  function generate_targets_section() {
    const config = FORM_STATE.config_schema;
    const targets = config.targets || {};

    return `
      <div class="form-section">
        <div class="section-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <circle cx="12" cy="12" r="6"/>
              <circle cx="12" cy="12" r="2"/>
            </svg>
            Targets
          </h3>
        </div>

        <div class="form-grid">
          <div class="form-field">
            <label class="field-label">Annual Target ($)</label>
            ${generate_tooltip('annual_target')}
            <div class="field-input">
              <input type="number" name="annual_target" value="${targets.annual_target || ''}" step="1000000" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Growth Rate</label>
            ${generate_tooltip('growth_rate')}
            <div class="field-input">
              <input type="number" name="growth_rate" value="${targets.growth_rate || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Target Source</label>
            ${generate_tooltip('target_source')}
            <div class="field-input">
              <select name="target_source" required>
                <option value="fixed" ${targets.target_source === 'fixed' ? 'selected' : ''}>Fixed</option>
                <option value="growth" ${targets.target_source === 'growth' ? 'selected' : ''}>Growth</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Planning Mode</label>
            ${generate_tooltip('planning_mode')}
            <div class="field-input">
              <select name="planning_mode" required>
                <option value="full_year" ${targets.planning_mode === 'full_year' ? 'selected' : ''}>Full Year</option>
                <option value="rolling_forward" ${targets.planning_mode === 'rolling_forward' ? 'selected' : ''}>Rolling Forward</option>
                <option value="manual_lock" ${targets.planning_mode === 'manual_lock' ? 'selected' : ''}>Manual Lock</option>
              </select>
            </div>
          </div>
        </div>

        <div class="form-subsection">
          <h4>Seasonality Weights</h4>
          ${generate_tooltip('seasonality_weights')}
          <div class="seasonality-grid">
            ${Object.entries(targets.seasonality_weights || {}).map(([month, weight]) => `
              <div class="form-field small">
                <label class="field-label">${format_label(month)}</label>
                <div class="field-input">
                  <input type="number" name="seasonality_${month}" value="${weight}" step="0.001" min="0" max="1" required>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Generate allocation section
   */
  function generate_allocation_section() {
    const config = FORM_STATE.config_schema;
    const allocation = config.allocation || {};

    return `
      <div class="form-section">
        <div class="section-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="7" width="20" height="14" rx="2" ry="2"/>
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
            </svg>
            Allocation
          </h3>
        </div>

        <div class="form-grid">
          <div class="form-field">
            <label class="field-label">Objective Metric</label>
            ${generate_tooltip('objective_metric')}
            <div class="field-input">
              <select name="objective_metric" required>
                <option value="bookings" ${allocation.objective?.metric === 'bookings' ? 'selected' : ''}>Bookings</option>
                <option value="pipeline" ${allocation.objective?.metric === 'pipeline' ? 'selected' : ''}>Pipeline</option>
                <option value="revenue" ${allocation.objective?.metric === 'revenue' ? 'selected' : ''}>Revenue</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Optimizer Mode</label>
            ${generate_tooltip('optimizer_mode')}
            <div class="field-input">
              <select name="optimizer_mode" required>
                <option value="greedy" ${allocation.optimizer_mode === 'greedy' ? 'selected' : ''}>Greedy (Fast)</option>
                <option value="solver" ${allocation.optimizer_mode === 'solver' ? 'selected' : ''}>Solver (Precise)</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Share Floor</label>
            ${generate_tooltip('share_floor')}
            <div class="field-input">
              <input type="number" name="share_floor" value="${allocation.constraints?.share_floor || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Share Ceiling</label>
            ${generate_tooltip('share_ceiling')}
            <div class="field-input">
              <input type="number" name="share_ceiling" value="${allocation.constraints?.share_ceiling || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Generate economics section
   */
  function generate_economics_section() {
    const config = FORM_STATE.config_schema;
    const economics = config.economics || {};
    const default_decay = economics.default_decay || {};

    return `
      <div class="form-section">
        <div class="section-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="1" x2="12" y2="23"/>
              <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
            </svg>
            Economics
          </h3>
        </div>

        <div class="form-grid">
          <div class="form-field">
            <div class="field-header">
              <label class="field-label">Use Calibration</label>
              <div class="field-controls">
                <label class="toggle-switch">
                  <input type="checkbox" name="use_calibration" ${economics.use_calibration ? 'checked' : ''}>
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>
            ${generate_tooltip('use_calibration')}
          </div>

          <div class="form-field">
            <div class="field-header">
              <label class="field-label">Cash Cycle Enabled</label>
              <div class="field-controls">
                <label class="toggle-switch">
                  <input type="checkbox" name="cash_cycle_enabled" ${economics.cash_cycle?.enabled ? 'checked' : ''}>
                  <span class="toggle-slider"></span>
                </label>
              </div>
            </div>
            ${generate_tooltip('cash_cycle_enabled')}
          </div>
        </div>

        <div class="form-subsection">
          <h4>ASP Decay</h4>
          <div class="form-grid">
            <div class="form-field">
              <label class="field-label">Function</label>
              ${generate_tooltip('asp_decay_function')}
              <div class="field-input">
                <select name="asp_decay_function">
                  <option value="exponential" ${default_decay.asp?.function === 'exponential' ? 'selected' : ''}>Exponential</option>
                  <option value="linear" ${default_decay.asp?.function === 'linear' ? 'selected' : ''}>Linear</option>
                  <option value="step" ${default_decay.asp?.function === 'step' ? 'selected' : ''}>Step</option>
                  <option value="none" ${default_decay.asp?.function === 'none' ? 'selected' : ''}>None</option>
                </select>
              </div>
            </div>

            <div class="form-field">
              <label class="field-label">Rate</label>
              ${generate_tooltip('asp_decay_rate')}
              <div class="field-input">
                <input type="number" name="asp_decay_rate" value="${default_decay.asp?.rate || ''}" step="0.0001" min="0">
              </div>
            </div>

            <div class="form-field">
              <label class="field-label">Threshold</label>
              ${generate_tooltip('asp_threshold')}
              <div class="field-input">
                <input type="number" name="asp_threshold" value="${default_decay.asp?.threshold || ''}" step="1" min="0">
              </div>
            </div>

            <div class="form-field">
              <label class="field-label">Floor Multiplier</label>
              ${generate_tooltip('asp_floor_multiplier')}
              <div class="field-input">
                <input type="number" name="asp_floor_multiplier" value="${default_decay.asp?.floor_multiplier || ''}" step="0.01" min="0" max="1">
              </div>
            </div>
          </div>
        </div>

        <div class="form-subsection">
          <h4>Win Rate Decay</h4>
          <div class="form-grid">
            <div class="form-field">
              <label class="field-label">Function</label>
              ${generate_tooltip('win_rate_decay_function')}
              <div class="field-input">
                <select name="win_rate_decay_function">
                  <option value="exponential" ${default_decay.win_rate?.function === 'exponential' ? 'selected' : ''}>Exponential</option>
                  <option value="linear" ${default_decay.win_rate?.function === 'linear' ? 'selected' : ''}>Linear</option>
                  <option value="step" ${default_decay.win_rate?.function === 'step' ? 'selected' : ''}>Step</option>
                  <option value="none" ${default_decay.win_rate?.function === 'none' ? 'selected' : ''}>None</option>
                </select>
              </div>
            </div>

            <div class="form-field">
              <label class="field-label">Rate</label>
              ${generate_tooltip('win_rate_decay_rate')}
              <div class="field-input">
                <input type="number" name="win_rate_decay_rate" value="${default_decay.win_rate?.rate || ''}" step="0.0001" min="0">
              </div>
            </div>

            <div class="form-field">
              <label class="field-label">Threshold</label>
              ${generate_tooltip('win_rate_threshold')}
              <div class="field-input">
                <input type="number" name="win_rate_threshold" value="${default_decay.win_rate?.threshold || ''}" step="1" min="0">
              </div>
            </div>

            <div class="form-field">
              <label class="field-label">Floor Multiplier</label>
              ${generate_tooltip('win_rate_floor_multiplier')}
              <div class="field-input">
                <input type="number" name="win_rate_floor_multiplier" value="${default_decay.win_rate?.floor_multiplier || ''}" step="0.01" min="0" max="1">
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Generate AE Model section
   */
  function generate_ae_model_section() {
    const config = FORM_STATE.config_schema;
    const ae_model = config.ae_model || {};

    return `
      <div class="form-section">
        <div class="section-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
              <circle cx="9" cy="7" r="4"/>
              <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
              <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
            </svg>
            AE Model
          </h3>
        </div>

        <div class="form-grid">
          <div class="form-field">
            <label class="field-label">Starting Headcount</label>
            ${generate_tooltip('starting_hc')}
            <div class="field-input">
              <input type="number" name="starting_hc" value="${ae_model.starting_hc || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Productivity per AE</label>
            ${generate_tooltip('productivity_per_ae')}
            <div class="field-input">
              <input type="number" name="productivity_per_ae" value="${ae_model.productivity_per_ae || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Ramp Duration (days)</label>
            ${generate_tooltip('ramp_duration_days')}
            <div class="field-input">
              <input type="number" name="ramp_duration_days" value="${ae_model.ramp?.duration_days || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Mentoring Overhead</label>
            ${generate_tooltip('mentoring_overhead')}
            <div class="field-input">
              <input type="number" name="mentoring_overhead" value="${ae_model.mentoring?.overhead_pct_per_new_hire || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Max Mentees per AE</label>
            ${generate_tooltip('max_mentees_per_ae')}
            <div class="field-input">
              <input type="number" name="max_mentees_per_ae" value="${ae_model.mentoring?.max_mentees_per_ae || ''}" step="1" min="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">PTO %</label>
            ${generate_tooltip('pto_pct')}
            <div class="field-input">
              <input type="number" name="pto_pct" value="${ae_model.shrinkage?.pto_pct || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Admin %</label>
            ${generate_tooltip('admin_pct')}
            <div class="field-input">
              <input type="number" name="admin_pct" value="${ae_model.shrinkage?.admin_pct || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Enablement Base %</label>
            ${generate_tooltip('enablement_base_pct')}
            <div class="field-input">
              <input type="number" name="enablement_base_pct" value="${ae_model.shrinkage?.enablement_base_pct || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Enablement Scaling</label>
            ${generate_tooltip('enablement_scaling')}
            <div class="field-input">
              <select name="enablement_scaling">
                <option value="proportional" ${ae_model.shrinkage?.enablement_scaling === 'proportional' ? 'selected' : ''}>Proportional</option>
                <option value="fixed" ${ae_model.shrinkage?.enablement_scaling === 'fixed' ? 'selected' : ''}>Fixed</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Attrition Rate</label>
            ${generate_tooltip('attrition_rate')}
            <div class="field-input">
              <input type="number" name="attrition_rate" value="${ae_model.attrition?.annual_rate || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Backfill Delay (months)</label>
            ${generate_tooltip('backfill_delay_months')}
            <div class="field-input">
              <input type="number" name="backfill_delay_months" value="${ae_model.attrition?.backfill_delay_months || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Stretch Threshold</label>
            ${generate_tooltip('stretch_threshold')}
            <div class="field-input">
              <input type="number" name="stretch_threshold" value="${ae_model.stretch_threshold || ''}" step="0.01" min="1" required>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Generate What-If Scenarios section
   */
  function generate_what_if_section() {
    const config = FORM_STATE.config_schema;
    const scenarios = config.what_if_scenarios || [];

    return `
      <div class="form-section">
        <div class="section-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            What-If Scenarios
          </h3>
        </div>

        <div class="scenarios-grid">
          ${scenarios.map((scenario, index) => `
            <div class="scenario-card">
              <div class="scenario-header">
                <div class="scenario-title">
                  <h4>${scenario.name || `Scenario ${index + 1}`}</h4>
                  <p class="scenario-description">${scenario.description || ''}</p>
                </div>
                <label class="toggle-switch">
                  <input type="checkbox" name="scenario_${index}_enabled" ${scenario.enabled ? 'checked' : ''}>
                  <span class="toggle-slider"></span>
                </label>
              </div>
              ${generate_tooltip('scenario_enabled')}
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  /**
   * Generate System section
   */
  function generate_system_section() {
    const config = FORM_STATE.config_schema;
    const system = config.system || {};

    return `
      <div class="form-section">
        <div class="section-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
              <line x1="8" y1="21" x2="16" y2="21"/>
              <line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
            System
          </h3>
        </div>

        <div class="form-grid">
          <div class="form-field">
            <label class="field-label">Output Directory</label>
            ${generate_tooltip('output_dir')}
            <div class="field-input">
              <input type="text" name="output_dir" value="${system.output_dir || ''}" required>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Solver Method</label>
            ${generate_tooltip('solver_method')}
            <div class="field-input">
              <select name="solver_method">
                <option value="SLSQP" ${system.solver?.method === 'SLSQP' ? 'selected' : ''}>SLSQP</option>
                <option value="trust-constr" ${system.solver?.method === 'trust-constr' ? 'selected' : ''}>Trust Constrained</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            <label class="field-label">Max Iterations</label>
            ${generate_tooltip('solver_max_iterations')}
            <div class="field-input">
              <input type="number" name="solver_max_iterations" value="${system.solver?.max_iterations || ''}" step="1" min="1" required>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Generate tooltip element
   */
  function generate_tooltip(field_key) {
    const tooltip = TOOLTIPS[field_key];
    if (!tooltip) return '';

    return `
      <div class="tooltip">
        <svg class="tooltip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <div class="tooltip-content">
          <strong>${tooltip.title}</strong>
          <p>${tooltip.description}</p>
          <p><strong>Impact:</strong> ${tooltip.impact}</p>
          <p><strong>Example:</strong> ${tooltip.example}</p>
        </div>
      </div>
    `;
  }

  /**
   * Format label for display
   */
  function format_label(key) {
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase());
  }

  /**
   * Setup event listeners
   */
  function setup_event_listeners() {
    const form = document.getElementById('configForm');
    if (!form) return;

    // Form submission - prevent duplicate listeners
    if (!form.hasAttribute('data-submit-listener')) {
      form.addEventListener('submit', handle_form_submit);
      form.setAttribute('data-submit-listener', 'true');
    }

    // Reset button
    const resetBtn = document.getElementById('resetBtn');
    if (resetBtn && !resetBtn.hasAttribute('data-reset-listener')) {
      resetBtn.addEventListener('click', handle_reset);
      resetBtn.setAttribute('data-reset-listener', 'true');
    }

  }

  /**
   * Validate entire form with detailed error reporting
   */
  function validate_form() {
    const form = document.getElementById('configForm');
    if (!form) return false;

    // Check seasonality weights sum
    const seasonality_inputs = form.querySelectorAll('[name^="seasonality_"]');
    let seasonality_sum = 0;
    seasonality_inputs.forEach(input => {
      seasonality_sum += parseFloat(input.value) || 0;
    });

    if (Math.abs(seasonality_sum - 1.0) > 0.001) {
      show_error('Seasonality weights must sum to 1.0.\n\nCurrent sum: ' + seasonality_sum.toFixed(3) + '\n\nPlease adjust the monthly weights so they add up to 1.0.');
      return false;
    }

    // Check share floor <= share ceiling
    const share_floor = parseFloat(form.querySelector('[name="share_floor"]')?.value);
    const share_ceiling = parseFloat(form.querySelector('[name="share_ceiling"]')?.value);
    if (share_floor >= share_ceiling) {
      show_error('Share floor must be less than share ceiling.\n\nCurrent values:\n• Share Floor: ' + share_floor + '\n• Share Ceiling: ' + share_ceiling + '\n\nPlease adjust these values so the floor is lower than the ceiling.');
      return false;
    }

    return form.checkValidity();
  }

  /**
   * Collect form data
   */
  function collect_form_data() {
    const form = document.getElementById('configForm');
    if (!form) return null;

    const formData = new FormData(form);
    const data = {};

    formData.forEach((value, key) => {
      data[key] = value;
    });

    return data;
  }

  /**
   * Handle form submission
   */
  async function handle_form_submit(event) {
    event.preventDefault();

    // Validate form
    if (!validate_form()) {
      return;
    }

    // Collect form data
    const form_data = collect_form_data();
    if (!form_data) {
      console.error('Config Form - Failed to collect form data');
      return;
    }

    // Show loading overlay with progress simulation
    if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.show) {
      LoadingOverlay.show({
        status: 'Initializing...',
        simulate_progress: true,
        simulation_speed: 100
      });
    }

    try {
      // Submit to backend
      const response = await fetch('/api/run-plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(form_data)
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || 'Plan execution failed');
      }

      if (typeof Logger !== 'undefined' && Logger.debug) {
        Logger.debug('ConfigForm', 'Plan executed successfully');
      }

      // Dispatch plan completion event for ChartViewer to handle
      const plan_complete_event = new CustomEvent('plancomplete', {
        detail: {
          version_id: result.version_id,
          chart_server_url: result.charts?.url || null
        },
        bubbles: true
      });
      document.dispatchEvent(plan_complete_event);

      // Complete loading overlay and switch to charts tab
      if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.complete) {
        LoadingOverlay.complete(() => {
          if (typeof TabManager !== 'undefined') {
            TabManager.switch_tab('charts');
          }
        });
      }

    } catch (error) {
      console.error('Config Form - Plan execution failed:', error);
      alert('Failed to run plan: ' + error.message);

      // Hide loading overlay on error
      if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.hide) {
        LoadingOverlay.hide();
      }
    }
  }

  /**
   * Handle reset to defaults
   */
  async function handle_reset() {
    if (!confirm('Are you sure you want to reset all fields to their default values?')) {
      return;
    }

    try {
      const response = await fetch('/api/config/defaults');
      if (!response.ok) {
        throw new Error('Failed to load defaults');
      }

      const defaults = await response.json();

      // Update form fields with defaults
      if (FORM_STATE.config_schema) {
        FORM_STATE.config_schema = defaults;
        generate_form();
        setup_event_listeners();
      }

    } catch (error) {
      console.error('Config Form - Failed to reset:', error);
      alert('Failed to reset form: ' + error.message);
    }
  }

  /**
   * Public API for the Config Form
   */
  window.ConfigForm = {
    initialize: initialize,
    is_loaded: () => FORM_STATE.is_loaded,
    get_form_data: collect_form_data,
    validate_form: validate_form
  };

})();
