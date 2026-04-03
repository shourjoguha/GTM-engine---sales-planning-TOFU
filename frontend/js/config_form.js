/* ── GTM Planning Engine - Configuration Form ── */

(function() {
  'use strict';

  const FORM_STATE = {
    config_schema: null,
    is_loaded: false,
    is_initializing: false,
    tooltip_popup: null,
    tooltip_listeners_initialized: false
  };

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
    hiring_plan: {
      title: "Hiring Tranches",
      description: "Define hiring counts and start month by tranche.",
      impact: "Controls when AE capacity enters the model.",
      example: "Add a tranche for month 6 with 8 hires."
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

  const DOM = {
    config_panel: null,
    form_container: null,
    error_display: null,
    error_text: null,
    error_dismiss_btn: null
  };

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
      update_seasonality_sum();
      update_planning_mode_controls();
      sync_hiring_tranche_count();

      FORM_STATE.is_loaded = true;
      if (typeof Logger !== 'undefined' && Logger.debug) {
        Logger.debug('ConfigForm', 'Initialized successfully');
      }
    } finally {
      FORM_STATE.is_initializing = false;
    }
  }

  function show_error(message) {
    if (DOM.error_text) {
      DOM.error_text.textContent = message;
    }
    if (DOM.error_display) {
      DOM.error_display.classList.remove('hidden');
    }
  }

  function hide_error() {
    if (DOM.error_display) {
      DOM.error_display.classList.add('hidden');
    }
  }

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

  function generate_targets_section() {
    const config = FORM_STATE.config_schema;
    const targets = config.targets || {};
    const planning_mode = targets.planning_mode || 'full_year';
    const rolling_start_month = get_rolling_start_month(targets);

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
            ${generate_field_label('Annual Target ($)', 'annual_target')}
            <div class="field-input">
              <input type="number" name="annual_target" value="${targets.annual_target || ''}" step="1000000" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Growth Rate', 'growth_rate')}
            <div class="field-input">
              <input type="number" name="growth_rate" value="${targets.growth_rate || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Target Source', 'target_source')}
            <div class="field-input">
              <select name="target_source" required>
                <option value="fixed" ${targets.target_source === 'fixed' ? 'selected' : ''}>Fixed</option>
                <option value="growth" ${targets.target_source === 'growth' ? 'selected' : ''}>Growth</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Planning Mode', 'planning_mode')}
            <div class="field-input">
              <select name="planning_mode" id="planningModeSelect" required>
                <option value="full_year" ${planning_mode === 'full_year' ? 'selected' : ''}>Full Year</option>
                <option value="rolling_forward" ${planning_mode === 'rolling_forward' ? 'selected' : ''}>Rolling Forward</option>
                <option value="manual_lock" ${planning_mode === 'manual_lock' ? 'selected' : ''}>Manual Lock</option>
              </select>
            </div>
          </div>
        </div>

        <div class="planning-mode-controls" id="planningModeControls">
          <div class="planning-control-block ${planning_mode === 'rolling_forward' ? '' : 'hidden'}" id="rollingForwardControls">
            <div class="planning-control-header">Rolling Forward Settings</div>
            <div class="form-grid planning-mode-grid">
              <div class="form-field">
                <label class="field-label">Roll Forward From Month</label>
                <div class="field-input">
                  <select name="rolling_start_month" id="rollingStartMonth">
                    ${build_month_options(rolling_start_month)}
                  </select>
                </div>
              </div>
              <div class="form-field">
                <label class="field-label">Actuals File</label>
                <div class="field-input">
                  <input type="text" name="actuals_file" value="${targets.actuals_file || ''}" placeholder="Path to actuals CSV">
                </div>
              </div>
            </div>
          </div>

          <div class="planning-control-block ${planning_mode === 'manual_lock' ? '' : 'hidden'}" id="manualLockControls">
            <div class="planning-control-header">Locked Months</div>
            <div class="locked-months-grid">
              ${Array.from({ length: 12 }, (_, index) => {
                const month_number = index + 1;
                const checked = Array.isArray(targets.locked_months) && targets.locked_months.includes(month_number);
                return `
                  <label class="month-chip">
                    <input type="checkbox" name="locked_month_${month_number}" ${checked ? 'checked' : ''}>
                    <span>Month ${month_number}</span>
                  </label>
                `;
              }).join('')}
            </div>
          </div>
        </div>

        <div class="form-subsection">
          <div class="subsection-header-row">
            <h4>Seasonality Weights</h4>
            ${generate_tooltip('seasonality_weights')}
            <span class="seasonality-sum-badge" id="seasonalitySumBadge">
              Sum: <strong id="seasonalitySumValue">0.0%</strong>
            </span>
          </div>
          <div class="seasonality-grid">
            ${Object.entries(targets.seasonality_weights || {}).map(([month, weight]) => `
              <div class="form-field small">
                <label class="field-label">${format_label(month)}</label>
                <div class="field-input">
                  <div class="percent-input-wrap">
                    <input type="number" class="seasonality-input" name="seasonality_pct_${month}" value="${to_percent(weight)}" step="0.1" min="0" required>
                    <span class="percent-symbol">%</span>
                  </div>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;
  }

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
            ${generate_field_label('Objective Metric', 'objective_metric')}
            <div class="field-input">
              <select name="objective_metric" required>
                <option value="bookings" ${allocation.objective?.metric === 'bookings' ? 'selected' : ''}>Bookings</option>
                <option value="pipeline" ${allocation.objective?.metric === 'pipeline' ? 'selected' : ''}>Pipeline</option>
                <option value="revenue" ${allocation.objective?.metric === 'revenue' ? 'selected' : ''}>Revenue</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Optimizer Mode', 'optimizer_mode')}
            <div class="field-input">
              <select name="optimizer_mode" required>
                <option value="greedy" ${allocation.optimizer_mode === 'greedy' ? 'selected' : ''}>Greedy (Fast)</option>
                <option value="solver" ${allocation.optimizer_mode === 'solver' ? 'selected' : ''}>Solver (Precise)</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Share Floor', 'share_floor')}
            <div class="field-input">
              <input type="number" name="share_floor" value="${allocation.constraints?.share_floor || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Share Ceiling', 'share_ceiling')}
            <div class="field-input">
              <input type="number" name="share_ceiling" value="${allocation.constraints?.share_ceiling || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>
        </div>
      </div>
    `;
  }

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
              ${generate_field_label('Function', 'asp_decay_function')}
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
              ${generate_field_label('Rate', 'asp_decay_rate')}
              <div class="field-input">
                <input type="number" name="asp_decay_rate" value="${default_decay.asp?.rate || ''}" step="0.0001" min="0">
              </div>
            </div>

            <div class="form-field">
              ${generate_field_label('Threshold', 'asp_threshold')}
              <div class="field-input">
                <input type="number" name="asp_threshold" value="${default_decay.asp?.threshold || ''}" step="1" min="0">
              </div>
            </div>

            <div class="form-field">
              ${generate_field_label('Floor Multiplier', 'asp_floor_multiplier')}
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
              ${generate_field_label('Function', 'win_rate_decay_function')}
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
              ${generate_field_label('Rate', 'win_rate_decay_rate')}
              <div class="field-input">
                <input type="number" name="win_rate_decay_rate" value="${default_decay.win_rate?.rate || ''}" step="0.0001" min="0">
              </div>
            </div>

            <div class="form-field">
              ${generate_field_label('Threshold', 'win_rate_threshold')}
              <div class="field-input">
                <input type="number" name="win_rate_threshold" value="${default_decay.win_rate?.threshold || ''}" step="1" min="0">
              </div>
            </div>

            <div class="form-field">
              ${generate_field_label('Floor Multiplier', 'win_rate_floor_multiplier')}
              <div class="field-input">
                <input type="number" name="win_rate_floor_multiplier" value="${default_decay.win_rate?.floor_multiplier || ''}" step="0.01" min="0" max="1">
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function generate_ae_model_section() {
    const config = FORM_STATE.config_schema;
    const ae_model = config.ae_model || {};
    const hiring_plan = Array.isArray(ae_model.hiring_plan) && ae_model.hiring_plan.length
      ? ae_model.hiring_plan
      : [{ count: 0, start_month: 1 }, { count: 0, start_month: 2 }, { count: 0, start_month: 3 }];

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
            ${generate_field_label('Starting Headcount', 'starting_hc')}
            <div class="field-input">
              <input type="number" name="starting_hc" value="${ae_model.starting_hc || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Productivity per AE', 'productivity_per_ae')}
            <div class="field-input">
              <input type="number" name="productivity_per_ae" value="${ae_model.productivity_per_ae || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Ramp Duration (days)', 'ramp_duration_days')}
            <div class="field-input">
              <input type="number" name="ramp_duration_days" value="${ae_model.ramp?.duration_days || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Mentoring Overhead', 'mentoring_overhead')}
            <div class="field-input">
              <input type="number" name="mentoring_overhead" value="${ae_model.mentoring?.overhead_pct_per_new_hire || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Max Mentees per AE', 'max_mentees_per_ae')}
            <div class="field-input">
              <input type="number" name="max_mentees_per_ae" value="${ae_model.mentoring?.max_mentees_per_ae || ''}" step="1" min="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('PTO %', 'pto_pct')}
            <div class="field-input">
              <input type="number" name="pto_pct" value="${ae_model.shrinkage?.pto_pct || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Admin %', 'admin_pct')}
            <div class="field-input">
              <input type="number" name="admin_pct" value="${ae_model.shrinkage?.admin_pct || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Enablement Base %', 'enablement_base_pct')}
            <div class="field-input">
              <input type="number" name="enablement_base_pct" value="${ae_model.shrinkage?.enablement_base_pct || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Enablement Scaling', 'enablement_scaling')}
            <div class="field-input">
              <select name="enablement_scaling">
                <option value="proportional" ${ae_model.shrinkage?.enablement_scaling === 'proportional' ? 'selected' : ''}>Proportional</option>
                <option value="fixed" ${ae_model.shrinkage?.enablement_scaling === 'fixed' ? 'selected' : ''}>Fixed</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Attrition Rate', 'attrition_rate')}
            <div class="field-input">
              <input type="number" name="attrition_rate" value="${ae_model.attrition?.annual_rate || ''}" step="0.01" min="0" max="1" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Backfill Delay (months)', 'backfill_delay_months')}
            <div class="field-input">
              <input type="number" name="backfill_delay_months" value="${ae_model.attrition?.backfill_delay_months || ''}" step="1" min="0" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Stretch Threshold', 'stretch_threshold')}
            <div class="field-input">
              <input type="number" name="stretch_threshold" value="${ae_model.stretch_threshold || ''}" step="0.01" min="1" required>
            </div>
          </div>
        </div>

        <div class="form-subsection">
          <div class="subsection-header-row">
            <h4>Hiring Tranches</h4>
            ${generate_tooltip('hiring_plan')}
          </div>
          <input type="hidden" id="aeHiringTrancheCount" value="${hiring_plan.length}">
          <div class="tranche-scroll-wrap">
            <div class="tranche-scroll" id="trancheScroll">
              ${hiring_plan.map((tranche, index) => generate_tranche_card(index, tranche)).join('')}
            </div>
          </div>
          <div class="tranche-actions">
            <button type="button" class="btn btn-secondary" id="addTrancheBtn">+ Add Tranche</button>
          </div>
        </div>
      </div>
    `;
  }

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
            <div class="scenario-card" data-scenario-index="${index}">
              <div class="scenario-header">
                <div class="scenario-title">
                  <h4>${get_display_scenario_name(scenario.name) || `Scenario ${index + 1}`}</h4>
                  <p class="scenario-description">${scenario.description || ''}</p>
                </div>
                <label class="toggle-switch">
                  <input type="checkbox" name="scenario_${index}_enabled" ${scenario.enabled ? 'checked' : ''}>
                  <span class="toggle-slider"></span>
                </label>
              </div>
              ${generate_tooltip('scenario_enabled')}
              <div class="scenario-perturbations">
                ${generate_scenario_perturbations(scenario, index)}
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

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
            ${generate_field_label('Output Directory', 'output_dir')}
            <div class="field-input">
              <input type="text" name="output_dir" value="${system.output_dir || ''}" required>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Solver Method', 'solver_method')}
            <div class="field-input">
              <select name="solver_method">
                <option value="SLSQP" ${system.solver?.method === 'SLSQP' ? 'selected' : ''}>SLSQP</option>
                <option value="trust-constr" ${system.solver?.method === 'trust-constr' ? 'selected' : ''}>Trust Constrained</option>
              </select>
            </div>
          </div>

          <div class="form-field">
            ${generate_field_label('Max Iterations', 'solver_max_iterations')}
            <div class="field-input">
              <input type="number" name="solver_max_iterations" value="${system.solver?.max_iterations || ''}" step="1" min="1" required>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function generate_field_label(label_text, field_key) {
    return `
      <div class="field-label-row">
        <label class="field-label">${label_text}</label>
        ${generate_tooltip(field_key)}
      </div>
    `;
  }

  function generate_tooltip(field_key) {
    const tooltip = TOOLTIPS[field_key];
    if (!tooltip) return '';

    return `
      <button type="button" class="tooltip-trigger" data-tooltip-key="${field_key}" aria-label="Open help for ${field_key}">
        <svg class="tooltip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
      </button>
    `;
  }

  function get_tooltip_html(field_key) {
    const tooltip = TOOLTIPS[field_key];
    if (!tooltip) {
      return '';
    }
    return `
      <strong>${tooltip.title}</strong>
      <p>${tooltip.description}</p>
      <p><strong>Impact:</strong> ${tooltip.impact}</p>
      <p><strong>Example:</strong> ${tooltip.example}</p>
    `;
  }

  function format_label(key) {
    return key
      .replace(/_/g, ' ')
      .replace(/\b\w/g, l => l.toUpperCase());
  }

  function to_percent(value) {
    return Number(((parseFloat(value) || 0) * 100).toFixed(1));
  }

  function build_month_options(selected_month) {
    return Array.from({ length: 12 }, (_, index) => {
      const month_number = index + 1;
      return `<option value="${month_number}" ${selected_month === month_number ? 'selected' : ''}>Month ${month_number}</option>`;
    }).join('');
  }

  function get_rolling_start_month(targets) {
    if (targets.planning_mode === 'rolling_forward' && Array.isArray(targets.locked_months) && targets.locked_months.length) {
      const max_locked = Math.max(...targets.locked_months);
      const next_month = Math.min(max_locked + 1, 12);
      return Number.isFinite(next_month) ? next_month : 1;
    }
    return 1;
  }

  function generate_tranche_card(index, tranche) {
    const count = parseInt(tranche.count, 10) || 0;
    const start_month = parseInt(tranche.start_month, 10) || 1;
    return `
      <div class="hiring-tranche" data-tranche-index="${index}">
        <div class="hiring-tranche-head">
          <span class="hiring-tranche-title">Tranche ${index + 1}</span>
          <button type="button" class="remove-tranche-btn" data-tranche-remove="${index}" ${index < 3 ? 'disabled' : ''}>×</button>
        </div>
        <div class="form-field">
          <label class="field-label">Count</label>
          <div class="field-input">
            <input type="number" class="tranche-count-input" min="0" step="1" value="${count}">
          </div>
        </div>
        <div class="form-field">
          <label class="field-label">Start Month</label>
          <div class="field-input">
            <select class="tranche-month-input">
              ${build_month_options(start_month)}
            </select>
          </div>
        </div>
      </div>
    `;
  }

  function generate_scenario_perturbations(scenario, scenario_index) {
    const perturbations = scenario.perturbations || {};
    return Object.entries(perturbations).map(([perturbation_key, perturbation_value], perturbation_index) => {
      const key_field = `<input type="hidden" name="scenario_${scenario_index}_perturbation_${perturbation_index}_key" value="${perturbation_key}">`;
      if (Array.isArray(perturbation_value)) {
        return `
          <div class="scenario-perturbation-field">
            <label class="field-label">${format_label(perturbation_key)}</label>
            ${key_field}
            <input type="text" name="scenario_${scenario_index}_perturbation_${perturbation_index}_list" value="${perturbation_value.join(', ')}">
          </div>
        `;
      }

      if (typeof perturbation_value === 'object' && perturbation_value !== null) {
        const entries = Object.entries(perturbation_value);
        return `
          <div class="scenario-perturbation-field">
            <label class="field-label">${format_label(perturbation_key)}</label>
            ${key_field}
            <input type="hidden" name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_count" value="${entries.length}">
            <div class="scenario-map-editor" data-scenario-index="${scenario_index}" data-perturbation-index="${perturbation_index}">
              ${entries.map(([map_key, map_value], entry_index) => `
                <div class="scenario-map-row">
                  <input type="text" class="scenario-map-key" name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_key_${entry_index}" value="${map_key}">
                  <input type="number" step="0.01" class="scenario-map-value" name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_value_${entry_index}" value="${map_value}">
                  <button type="button" class="scenario-map-remove">×</button>
                </div>
              `).join('')}
            </div>
            <button type="button" class="btn btn-secondary add-scenario-map-entry" data-scenario-index="${scenario_index}" data-perturbation-index="${perturbation_index}">+ Add ${format_label(perturbation_key)} entry</button>
          </div>
        `;
      }

      return `
        <div class="scenario-perturbation-field">
          <label class="field-label">${format_label(perturbation_key)}</label>
          ${key_field}
          <input type="${typeof perturbation_value === 'number' ? 'number' : 'text'}" ${typeof perturbation_value === 'number' ? 'step="0.01"' : ''} name="scenario_${scenario_index}_perturbation_${perturbation_index}_value" value="${perturbation_value}">
        </div>
      `;
    }).join('');
  }

  function get_display_scenario_name(name) {
    const overrides = {
      'EOR pricing pressure': 'Pricing Pressure',
      'Q2 attrition spike': 'Attrition Spike',
      'Marketing budget cut': 'Channel Budget Cut'
    };
    return overrides[name] || name;
  }

  function setup_event_listeners() {
    const form = document.getElementById('configForm');
    if (!form) return;

    if (!form.hasAttribute('data-submit-listener')) {
      form.addEventListener('submit', handle_form_submit);
      form.setAttribute('data-submit-listener', 'true');
    }

    const resetBtn = document.getElementById('resetBtn');
    if (resetBtn && !resetBtn.hasAttribute('data-reset-listener')) {
      resetBtn.addEventListener('click', handle_reset);
      resetBtn.setAttribute('data-reset-listener', 'true');
    }

    const planning_mode_select = document.getElementById('planningModeSelect');
    if (planning_mode_select && !planning_mode_select.hasAttribute('data-planning-listener')) {
      planning_mode_select.addEventListener('change', update_planning_mode_controls);
      planning_mode_select.setAttribute('data-planning-listener', 'true');
    }

    form.addEventListener('input', event => {
      if (event.target?.classList?.contains('seasonality-input')) {
        update_seasonality_sum();
      }
    });

    const add_tranche_btn = document.getElementById('addTrancheBtn');
    if (add_tranche_btn && !add_tranche_btn.hasAttribute('data-tranche-listener')) {
      add_tranche_btn.addEventListener('click', add_hiring_tranche);
      add_tranche_btn.setAttribute('data-tranche-listener', 'true');
    }

    form.addEventListener('click', event => {
      const remove_tranche_btn = event.target.closest('.remove-tranche-btn');
      if (remove_tranche_btn && !remove_tranche_btn.disabled) {
        remove_tranche_btn.closest('.hiring-tranche')?.remove();
        reindex_hiring_tranches();
        sync_hiring_tranche_count();
        return;
      }

      const add_map_entry_btn = event.target.closest('.add-scenario-map-entry');
      if (add_map_entry_btn) {
        add_scenario_map_entry(add_map_entry_btn);
        return;
      }

      const remove_map_entry_btn = event.target.closest('.scenario-map-remove');
      if (remove_map_entry_btn) {
        const editor = remove_map_entry_btn.closest('.scenario-map-editor');
        remove_map_entry_btn.closest('.scenario-map-row')?.remove();
        sync_scenario_map_count(editor);
      }
    });

    setup_tooltip_system();
  }

  function setup_tooltip_system() {
    if (FORM_STATE.tooltip_listeners_initialized) {
      return;
    }
    if (!FORM_STATE.tooltip_popup) {
      const tooltip_popup = document.createElement('div');
      tooltip_popup.id = 'floatingTooltip';
      tooltip_popup.className = 'floating-tooltip hidden';
      document.body.appendChild(tooltip_popup);
      FORM_STATE.tooltip_popup = tooltip_popup;
    }

    document.addEventListener('mouseover', event => {
      const trigger = event.target.closest('.tooltip-trigger');
      if (!trigger) return;
      show_tooltip(trigger);
    });

    document.addEventListener('focusin', event => {
      const trigger = event.target.closest('.tooltip-trigger');
      if (!trigger) return;
      show_tooltip(trigger);
    });

    document.addEventListener('mouseout', event => {
      const trigger = event.target.closest('.tooltip-trigger');
      if (!trigger) return;
      const related = event.relatedTarget;
      if (related && related.closest('.tooltip-trigger') === trigger) {
        return;
      }
      hide_tooltip();
    });

    document.addEventListener('focusout', event => {
      if (event.target.closest('.tooltip-trigger')) {
        hide_tooltip();
      }
    });

    window.addEventListener('scroll', hide_tooltip, true);
    window.addEventListener('resize', hide_tooltip);
    document.addEventListener('click', event => {
      if (!event.target.closest('.tooltip-trigger')) {
        hide_tooltip();
      }
    });
    FORM_STATE.tooltip_listeners_initialized = true;
  }

  function show_tooltip(trigger) {
    const field_key = trigger.getAttribute('data-tooltip-key');
    const tooltip_html = get_tooltip_html(field_key);
    if (!tooltip_html || !FORM_STATE.tooltip_popup) {
      return;
    }

    FORM_STATE.tooltip_popup.innerHTML = tooltip_html;
    FORM_STATE.tooltip_popup.classList.remove('hidden');
    position_tooltip(trigger);
  }

  function hide_tooltip() {
    if (FORM_STATE.tooltip_popup) {
      FORM_STATE.tooltip_popup.classList.add('hidden');
    }
  }

  function position_tooltip(trigger) {
    if (!FORM_STATE.tooltip_popup) return;
    const popup = FORM_STATE.tooltip_popup;
    const trigger_rect = trigger.getBoundingClientRect();
    const popup_rect = popup.getBoundingClientRect();
    const viewport_width = window.innerWidth;
    const viewport_height = window.innerHeight;
    const spacing = 10;

    let top = trigger_rect.bottom + spacing;
    let left = trigger_rect.left + (trigger_rect.width / 2) - (popup_rect.width / 2);

    if (left < spacing) {
      left = spacing;
    } else if (left + popup_rect.width > viewport_width - spacing) {
      left = viewport_width - popup_rect.width - spacing;
    }

    if (top + popup_rect.height > viewport_height - spacing) {
      top = trigger_rect.top - popup_rect.height - spacing;
    }

    if (top < spacing) {
      top = spacing;
    }

    popup.style.top = `${top + window.scrollY}px`;
    popup.style.left = `${left + window.scrollX}px`;
  }

  function update_planning_mode_controls() {
    const select = document.getElementById('planningModeSelect');
    const rolling_controls = document.getElementById('rollingForwardControls');
    const manual_controls = document.getElementById('manualLockControls');
    if (!select || !rolling_controls || !manual_controls) {
      return;
    }

    const mode = select.value;
    rolling_controls.classList.toggle('hidden', mode !== 'rolling_forward');
    manual_controls.classList.toggle('hidden', mode !== 'manual_lock');
  }

  function update_seasonality_sum() {
    const inputs = document.querySelectorAll('.seasonality-input');
    const sum_badge = document.getElementById('seasonalitySumBadge');
    const sum_value = document.getElementById('seasonalitySumValue');
    if (!sum_badge || !sum_value) {
      return;
    }

    let total = 0;
    inputs.forEach(input => {
      total += parseFloat(input.value) || 0;
    });
    sum_value.textContent = `${total.toFixed(1)}%`;
    sum_badge.classList.toggle('seasonality-over-limit', total > 100);
    sum_badge.classList.toggle('seasonality-valid', Math.abs(total - 100) <= 0.1);
  }

  function add_hiring_tranche() {
    const container = document.getElementById('trancheScroll');
    if (!container) return;
    const next_index = container.querySelectorAll('.hiring-tranche').length;
    container.insertAdjacentHTML('beforeend', generate_tranche_card(next_index, { count: 0, start_month: 1 }));
    reindex_hiring_tranches();
    sync_hiring_tranche_count();
    const last_tranche = container.querySelector('.hiring-tranche:last-child');
    if (last_tranche) {
      last_tranche.scrollIntoView({ behavior: 'smooth', inline: 'end', block: 'nearest' });
    }
  }

  function reindex_hiring_tranches() {
    const tranches = document.querySelectorAll('.hiring-tranche');
    tranches.forEach((tranche, index) => {
      tranche.setAttribute('data-tranche-index', index);
      const title = tranche.querySelector('.hiring-tranche-title');
      if (title) {
        title.textContent = `Tranche ${index + 1}`;
      }
      const remove_btn = tranche.querySelector('.remove-tranche-btn');
      if (remove_btn) {
        remove_btn.setAttribute('data-tranche-remove', index);
        remove_btn.disabled = index < 3;
      }
    });
  }

  function sync_hiring_tranche_count() {
    const count_input = document.getElementById('aeHiringTrancheCount');
    if (count_input) {
      count_input.value = document.querySelectorAll('.hiring-tranche').length;
    }
  }

  function add_scenario_map_entry(button) {
    const scenario_index = button.getAttribute('data-scenario-index');
    const perturbation_index = button.getAttribute('data-perturbation-index');
    const editor = document.querySelector(`.scenario-map-editor[data-scenario-index="${scenario_index}"][data-perturbation-index="${perturbation_index}"]`);
    if (!editor) return;
    const next_index = editor.querySelectorAll('.scenario-map-row').length;
    editor.insertAdjacentHTML('beforeend', `
      <div class="scenario-map-row">
        <input type="text" class="scenario-map-key" name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_key_${next_index}" value="">
        <input type="number" step="0.01" class="scenario-map-value" name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_value_${next_index}" value="1">
        <button type="button" class="scenario-map-remove">×</button>
      </div>
    `);
    sync_scenario_map_count(editor);
  }

  function sync_scenario_map_count(editor) {
    if (!editor) return;
    const scenario_index = editor.getAttribute('data-scenario-index');
    const perturbation_index = editor.getAttribute('data-perturbation-index');
    const count_input = document.querySelector(`[name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_count"]`);
    if (count_input) {
      count_input.value = editor.querySelectorAll('.scenario-map-row').length;
    }
  }

  function validate_form() {
    const form = document.getElementById('configForm');
    if (!form) return false;

    const seasonality_inputs = form.querySelectorAll('.seasonality-input');
    let seasonality_sum_pct = 0;
    seasonality_inputs.forEach(input => {
      seasonality_sum_pct += parseFloat(input.value) || 0;
    });

    if (Math.abs(seasonality_sum_pct - 100) > 0.1) {
      show_error('Seasonality weights must sum to 100%.\n\nCurrent sum: ' + seasonality_sum_pct.toFixed(1) + '%\n\nPlease adjust the monthly weights so they add up to 100%.');
      return false;
    }

    const share_floor = parseFloat(form.querySelector('[name="share_floor"]')?.value);
    const share_ceiling = parseFloat(form.querySelector('[name="share_ceiling"]')?.value);
    if (share_floor >= share_ceiling) {
      show_error('Share floor must be less than share ceiling.\n\nCurrent values:\n• Share Floor: ' + share_floor + '\n• Share Ceiling: ' + share_ceiling + '\n\nPlease adjust these values so the floor is lower than the ceiling.');
      return false;
    }

    const planning_mode = form.querySelector('[name="planning_mode"]')?.value;
    if (planning_mode === 'manual_lock') {
      const locked_months = Array.from(form.querySelectorAll('[name^="locked_month_"]:checked'));
      if (!locked_months.length) {
        show_error('Manual lock mode requires at least one locked month.');
        return false;
      }
    }

    return form.checkValidity();
  }

  function collect_form_data() {
    const form = document.getElementById('configForm');
    const schema = FORM_STATE.config_schema;
    if (!form || !schema) return null;

    const config_payload = JSON.parse(JSON.stringify(schema));

    Object.entries(config_payload.dimensions || {}).forEach(([dimension_key, dimension_config]) => {
      dimension_config.enabled = !!form.querySelector(`[name="${dimension_key}_enabled"]`)?.checked;
    });

    const targets = config_payload.targets || {};
    targets.annual_target = parseFloat(form.querySelector('[name="annual_target"]')?.value || 0);
    targets.growth_rate = parseFloat(form.querySelector('[name="growth_rate"]')?.value || 0);
    targets.target_source = form.querySelector('[name="target_source"]')?.value || 'growth';
    targets.planning_mode = form.querySelector('[name="planning_mode"]')?.value || 'full_year';

    const seasonality_weights = {};
    form.querySelectorAll('.seasonality-input').forEach(input => {
      const month_key = input.name.replace('seasonality_pct_', '');
      seasonality_weights[month_key] = (parseFloat(input.value) || 0) / 100;
    });
    targets.seasonality_weights = seasonality_weights;

    if (targets.planning_mode === 'manual_lock') {
      targets.locked_months = Array.from(form.querySelectorAll('[name^="locked_month_"]:checked')).map(input => parseInt(input.name.replace('locked_month_', ''), 10)).filter(Number.isFinite);
    } else if (targets.planning_mode === 'rolling_forward') {
      const start_month = parseInt(form.querySelector('[name="rolling_start_month"]')?.value || '1', 10);
      targets.locked_months = Array.from({ length: Math.max(start_month - 1, 0) }, (_, index) => index + 1);
    } else {
      targets.locked_months = [];
    }

    const actuals_file_value = (form.querySelector('[name="actuals_file"]')?.value || '').trim();
    targets.actuals_file = actuals_file_value || null;
    config_payload.targets = targets;

    const allocation = config_payload.allocation || {};
    allocation.objective = allocation.objective || {};
    allocation.constraints = allocation.constraints || {};
    allocation.objective.metric = form.querySelector('[name="objective_metric"]')?.value || 'bookings';
    allocation.optimizer_mode = form.querySelector('[name="optimizer_mode"]')?.value || 'solver';
    allocation.constraints.share_floor = parseFloat(form.querySelector('[name="share_floor"]')?.value || 0);
    allocation.constraints.share_ceiling = parseFloat(form.querySelector('[name="share_ceiling"]')?.value || 0);
    config_payload.allocation = allocation;

    const economics = config_payload.economics || {};
    economics.default_decay = economics.default_decay || {};
    economics.default_decay.asp = economics.default_decay.asp || {};
    economics.default_decay.win_rate = economics.default_decay.win_rate || {};
    economics.cash_cycle = economics.cash_cycle || {};
    economics.use_calibration = !!form.querySelector('[name="use_calibration"]')?.checked;
    economics.cash_cycle.enabled = !!form.querySelector('[name="cash_cycle_enabled"]')?.checked;
    economics.default_decay.asp.function = form.querySelector('[name="asp_decay_function"]')?.value || 'exponential';
    economics.default_decay.asp.rate = parseFloat(form.querySelector('[name="asp_decay_rate"]')?.value || 0);
    economics.default_decay.asp.threshold = parseFloat(form.querySelector('[name="asp_threshold"]')?.value || 0);
    economics.default_decay.asp.floor_multiplier = parseFloat(form.querySelector('[name="asp_floor_multiplier"]')?.value || 0);
    economics.default_decay.win_rate.function = form.querySelector('[name="win_rate_decay_function"]')?.value || 'linear';
    economics.default_decay.win_rate.rate = parseFloat(form.querySelector('[name="win_rate_decay_rate"]')?.value || 0);
    economics.default_decay.win_rate.threshold = parseFloat(form.querySelector('[name="win_rate_threshold"]')?.value || 0);
    economics.default_decay.win_rate.floor_multiplier = parseFloat(form.querySelector('[name="win_rate_floor_multiplier"]')?.value || 0);
    config_payload.economics = economics;

    const ae_model = config_payload.ae_model || {};
    ae_model.ramp = ae_model.ramp || {};
    ae_model.mentoring = ae_model.mentoring || {};
    ae_model.shrinkage = ae_model.shrinkage || {};
    ae_model.attrition = ae_model.attrition || {};
    ae_model.starting_hc = parseInt(form.querySelector('[name="starting_hc"]')?.value || 0, 10);
    ae_model.productivity_per_ae = parseFloat(form.querySelector('[name="productivity_per_ae"]')?.value || 0);
    ae_model.ramp.duration_days = parseInt(form.querySelector('[name="ramp_duration_days"]')?.value || 0, 10);
    ae_model.mentoring.overhead_pct_per_new_hire = parseFloat(form.querySelector('[name="mentoring_overhead"]')?.value || 0);
    ae_model.mentoring.max_mentees_per_ae = parseInt(form.querySelector('[name="max_mentees_per_ae"]')?.value || 0, 10);
    ae_model.shrinkage.pto_pct = parseFloat(form.querySelector('[name="pto_pct"]')?.value || 0);
    ae_model.shrinkage.admin_pct = parseFloat(form.querySelector('[name="admin_pct"]')?.value || 0);
    ae_model.shrinkage.enablement_base_pct = parseFloat(form.querySelector('[name="enablement_base_pct"]')?.value || 0);
    ae_model.shrinkage.enablement_scaling = form.querySelector('[name="enablement_scaling"]')?.value || 'fixed';
    ae_model.attrition.annual_rate = parseFloat(form.querySelector('[name="attrition_rate"]')?.value || 0);
    ae_model.attrition.backfill_delay_months = parseInt(form.querySelector('[name="backfill_delay_months"]')?.value || 0, 10);
    ae_model.stretch_threshold = parseFloat(form.querySelector('[name="stretch_threshold"]')?.value || 1);

    const hiring_plan = [];
    form.querySelectorAll('.hiring-tranche').forEach(tranche => {
      const count = parseInt(tranche.querySelector('.tranche-count-input')?.value || 0, 10);
      const start_month = parseInt(tranche.querySelector('.tranche-month-input')?.value || 1, 10);
      if (Number.isFinite(count) && Number.isFinite(start_month)) {
        hiring_plan.push({ count, start_month });
      }
    });
    ae_model.hiring_plan = hiring_plan;
    config_payload.ae_model = ae_model;

    const scenarios = (config_payload.what_if_scenarios || []).map((scenario, scenario_index) => {
      const next_scenario = JSON.parse(JSON.stringify(scenario));
      next_scenario.enabled = !!form.querySelector(`[name="scenario_${scenario_index}_enabled"]`)?.checked;
      const perturbations = scenario.perturbations || {};
      const next_perturbations = {};
      Object.entries(perturbations).forEach(([perturbation_key, perturbation_value], perturbation_index) => {
        if (Array.isArray(perturbation_value)) {
          const list_value = form.querySelector(`[name="scenario_${scenario_index}_perturbation_${perturbation_index}_list"]`)?.value || '';
          next_perturbations[perturbation_key] = list_value
            .split(',')
            .map(item => item.trim())
            .filter(Boolean)
            .map(item => {
              const parsed = Number(item);
              return Number.isFinite(parsed) ? parsed : item;
            });
          return;
        }

        if (typeof perturbation_value === 'object' && perturbation_value !== null) {
          const map_count = parseInt(form.querySelector(`[name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_count"]`)?.value || '0', 10);
          const map_value = {};
          for (let map_index = 0; map_index < map_count; map_index++) {
            const key_input = form.querySelector(`[name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_key_${map_index}"]`);
            const value_input = form.querySelector(`[name="scenario_${scenario_index}_perturbation_${perturbation_index}_map_value_${map_index}"]`);
            if (!key_input || !value_input) continue;
            const map_key = key_input.value.trim();
            if (!map_key) continue;
            const parsed_value = parseFloat(value_input.value);
            map_value[map_key] = Number.isFinite(parsed_value) ? parsed_value : 0;
          }
          next_perturbations[perturbation_key] = map_value;
          return;
        }

        const scalar_input = form.querySelector(`[name="scenario_${scenario_index}_perturbation_${perturbation_index}_value"]`)?.value;
        if (typeof perturbation_value === 'number') {
          const parsed_scalar = parseFloat(scalar_input);
          next_perturbations[perturbation_key] = Number.isFinite(parsed_scalar) ? parsed_scalar : perturbation_value;
          return;
        }
        const cleaned_scalar = typeof scalar_input === 'string' ? scalar_input.trim() : '';
        next_perturbations[perturbation_key] = cleaned_scalar || perturbation_value;
      });
      next_scenario.perturbations = next_perturbations;
      return next_scenario;
    });
    config_payload.what_if_scenarios = scenarios;

    const system = config_payload.system || {};
    system.solver = system.solver || {};
    system.output_dir = form.querySelector('[name="output_dir"]')?.value || system.output_dir;
    system.solver.method = form.querySelector('[name="solver_method"]')?.value || system.solver.method;
    system.solver.max_iterations = parseInt(form.querySelector('[name="solver_max_iterations"]')?.value || system.solver.max_iterations || 1000, 10);
    config_payload.system = system;

    return {
      description: 'UI Run',
      mode: 'full',
      optimizer: allocation.optimizer_mode || 'solver',
      annual_target: targets.annual_target,
      auto_start_charts: true,
      config_updates: config_payload
    };
  }

  async function handle_form_submit(event) {
    event.preventDefault();

    if (!validate_form()) {
      return;
    }

    const form_data = collect_form_data();
    if (!form_data) {
      console.error('Config Form - Failed to collect form data');
      return;
    }

    if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.show) {
      LoadingOverlay.show({
        status: 'Initializing...',
        simulate_progress: true,
        simulation_speed: 100
      });
    }

    try {
      const response = await fetch('/api/run-plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(form_data)
      });

      const result = await response.json();

      if (!response.ok) {
        const error_text = result.details ? `${result.error || 'Plan execution failed'}\n\n${result.details}` : (result.error || 'Plan execution failed');
        throw new Error(error_text);
      }

      if (typeof Logger !== 'undefined' && Logger.debug) {
        Logger.debug('ConfigForm', 'Plan executed successfully');
      }

      const plan_complete_event = new CustomEvent('plancomplete', {
        detail: {
          version_id: result.version_id,
          chart_server_url: result.charts?.url || null
        },
        bubbles: true
      });
      document.dispatchEvent(plan_complete_event);

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

      if (typeof LoadingOverlay !== 'undefined' && LoadingOverlay.hide) {
        LoadingOverlay.hide();
      }
    }
  }

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

      if (FORM_STATE.config_schema) {
        FORM_STATE.config_schema = defaults;
        generate_form();
        setup_event_listeners();
        update_seasonality_sum();
        update_planning_mode_controls();
        sync_hiring_tranche_count();
      }

    } catch (error) {
      console.error('Config Form - Failed to reset:', error);
      alert('Failed to reset form: ' + error.message);
    }
  }

  window.ConfigForm = {
    initialize: initialize,
    is_loaded: () => FORM_STATE.is_loaded,
    get_form_data: collect_form_data,
    validate_form: validate_form
  };

})();
