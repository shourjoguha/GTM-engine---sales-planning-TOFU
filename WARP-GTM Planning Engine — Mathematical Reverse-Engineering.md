# GTM Planning Engine — Mathematical Reverse-Engineering

---

## A. Repository Math Overview

This repository implements a **constrained allocation optimizer for Go-To-Market (GTM) planning**. It answers the question: *"Given an annual revenue target and a team of sales reps selling multiple products through multiple channels, how should we distribute Sales Accepted Opportunities (SAOs) across product-channel segments each month to maximize bookings?"*

### Calculation Chain

| Step | Operation | Description |
|------|-----------|-------------|
| 1 | **Derive annual target** | From either a fixed value or prior-year growth |
| 2 | **Distribute target across months** | Using seasonality weights |
| 3 | **Model AE workforce capacity** | Month-by-month (hiring, ramp, mentoring, shrinkage, attrition) |
| 4 | **Compute baseline economics** | ASP, win rate per segment from historical actuals |
| 5 | **Apply decay curves** | As more SAOs are pushed into a segment, ASP and win rate degrade |
| 6 | **Optimize share allocation** | Across segments (greedy or SLSQP solver) to maximize weighted ROI subject to share floor/ceiling constraints and capacity limits |
| 7 | **Apply cash cycle delays** | SAOs don't convert to bookings instantly; products have different realization schedules. Late-month SAOs may produce deferred bookings beyond the planning horizon |
| 8 | **Validate** | The plan (revenue identity, share constraints, capacity, target alignment) |
| 9 | **Analyze recovery** | If any quarter misses target, redistribute shortfall across remaining quarters |

The engine produces **9 segments** (3 products × 3 channels: CM, EOR, Payroll × Marketing, Outbound, Partner) × **12 months** = **108 allocation rows** per plan run, plus aggregated summaries.

---

## B. Execution Order

### Pipeline Stages (invoked by `run_plan.py`)

| Stage | Module | Purpose |
|-------|--------|---------|
| 1 | `config_manager.py` | Load and validate YAML config |
| 2 | `data_loader.py` | Load raw actuals CSV, clean, confidence-score, compute segment baselines |
| 3 | `target_generator.py` | Distribute annual target across 12 months using seasonality weights |
| 4 | `ae_capacity.py` | Model monthly AE headcount and effective SAO capacity |
| 5 | `economics_engine.py` | Initialize decay curves, load baselines from step 2 |
| 6 | `optimizer.py` | Run allocation optimization (greedy or solver) for each month |
| 7 | `validation.py` | Run mathematical consistency checks on the allocation |
| 8 | `recovery.py` | Quarterly shortfall analysis and redistribution modeling |

### Modules Not in Pipeline (present in codebase)

| Module | Purpose |
|--------|---------|
| `adjustments.py` | Mid-cycle re-planning (lock actuals, revise targets, re-optimize) |
| `comparator.py` | Multi-dimensional comparison of two or more plan versions (HHI, volatility, stretch, confidence) |
| `what_if.py` | Named scenario perturbation engine (attrition spikes, pricing pressure, budget cuts, hiring freezes, new market entry) |
| `version_store.py` | Persistence (config snapshot, results CSV, summary JSON per version) |
| `utils.py` | Shared helpers (config hashing, currency formatting) |

---

## C. Config-to-Output Map

### Dimensions

| Config Key | Effect |
|------------|--------|
| `dimensions.product.enabled` / `dimensions.channel.enabled` | Determines which columns form segment keys → affects segment count in optimizer (currently 9 = 3×3) |
| `dimensions.region.enabled` / `dimensions.segment.enabled` / `dimensions.deal_type.enabled` | Currently disabled; if enabled would multiply segment count |

---

### Targets

| Config Key | Value | Effect |
|------------|-------|--------|
| `targets.annual_target` | $188M | Used when `target_source = "fixed"` → direct input to target generator → determines scale of all downstream SAO/bookings numbers |
| `targets.growth_rate` | 0.50 | Used when `target_source = "growth"` → `annual_target = prior_year_actuals × (1 + growth_rate)` = $125M × 1.5 = $187.5M |
| `targets.prior_year_actuals` | $125M | Base for growth derivation |
| `targets.target_source` | "growth" | Switch between fixed and growth-derived target |
| `targets.seasonality_weights` | month_1..month_12 | Each weight × annual_target = monthly target; must sum to 1.0 |
| `targets.planning_mode` | "full_year" | Controls whether months are locked (rolling_forward, manual_lock) |
| `targets.locked_months` | — | Which months to freeze in manual_lock mode |

---

### Allocation

| Config Key | Value | Effect |
|------------|-------|--------|
| `allocation.objective.metric` | "bookings" | What the optimizer maximizes (bookings = SAOs × ASP × CW) |
| `allocation.constraints.share_floor` | 0.03 | Minimum share per segment per month; hard constraint |
| `allocation.constraints.share_ceiling` | 0.40 | Maximum share per segment per month; hard constraint |
| `allocation.optimizer_mode` | "solver" | "greedy" or "solver" (SLSQP) |
| `allocation.objective.pipeline_to_bookings_ratio` | 0.40 | Used for metric conversion, not in main pipeline |

---

### Economics — Decay

| Config Key | Value | Effect |
|------------|-------|--------|
| `economics.default_decay.asp.function` | "exponential" | Decay shape for ASP |
| `economics.default_decay.asp.rate` | 0.0010 | Rate parameter: `ASP_eff = ASP_base × exp(-0.001 × max(0, volume - threshold))` |
| `economics.default_decay.asp.threshold` | 340 | SAO volume below which no decay applies |
| `economics.default_decay.asp.floor_multiplier` | 0.75 | ASP never drops below 75% of base |
| `economics.default_decay.win_rate.function` | "linear" | Decay shape for CW rate |
| `economics.default_decay.win_rate.rate` | 0.005 | `CW_eff = CW_base - 0.005 × max(0, volume - 260)` |
| `economics.default_decay.win_rate.threshold` | 260 | Volume below which win rate is constant |
| `economics.default_decay.win_rate.floor_multiplier` | 0.80 | CW never drops below 80% of base |

---

### Economics — Baselines

| Config Key | Value | Effect |
|------------|-------|--------|
| `economics.baseline.aggregation` | "median" | How base ASP and CW are derived from actuals (median across months per segment) |
| `economics.baseline.grain` | "segment" | One baseline per product×channel combo |
| `economics.baseline.source` | "actuals" | Compute from raw data (vs. manual override) |

---

### Economics — Cash Cycle

| Config Key | Value | Effect |
|------------|-------|--------|
| `economics.cash_cycle.enabled` | true | Activates time-delay booking realization |
| `economics.cash_cycle.product_overrides.EOR` | {0: 0.10, 1: 0.30, 2: 0.40, 3: 0.20} | EOR SAOs take 2-3 months to close |
| `economics.cash_cycle.product_overrides.CM` | {0: 0.40, 1: 0.35, 2: 0.15, 3: 0.10} | CM closes faster |
| `economics.cash_cycle.product_overrides.Payroll` | {0: 0.50, 1: 0.30, 2: 0.20} | Payroll medium cycle |
| `economics.cash_cycle.planning_horizon_months` | 12 | Bookings landing after month 12 are "deferred" |

**Mathematical effect**: In-window factor for month m = Σ(probability where m + delay ≤ 12). The optimizer weights marginal ROI by this factor, steering late-month allocation toward shorter-cycle products.

---

### Economics — Confidence

| Config Key | Value | Effect |
|------------|-------|--------|
| `economics.confidence.high_threshold` | 6 | ≥6 data rows per segment = high confidence |
| `economics.confidence.medium_threshold` | 3 | ≥3 = medium |
| `economics.confidence.default_fallback_multiplier` | 0.80 | Low-confidence segments get 80% of global average for missing metrics |

---

### AE Model

| Config Key | Value | Effect |
|------------|-------|--------|
| `ae_model.starting_hc` | 100 | Initial tenured AEs |
| `ae_model.productivity_per_ae` | 45 | SAOs per fully-ramped AE per month |
| `ae_model.hiring_plan` | 4 tranches | 25 in month 1, 25 in month 2, 5 in month 4, 6 in month 6 = 61 new hires |
| `ae_model.ramp.duration_days` | 45 | Days to reach full productivity (1.5 months) |
| `ae_model.mentoring.overhead_pct_per_new_hire` | 0.05 | 5% of a tenured AE's time per mentee |
| `ae_model.mentoring.max_mentees_per_ae` | 3 | Cap on mentoring load |
| `ae_model.shrinkage` | pto=0.08, admin=0.05, enablement=0.03 | Total static shrinkage = 16% |
| `ae_model.attrition.annual_rate` | 0.10 | 10%/year → ~0.833%/month applied to tenured pool |
| `ae_model.stretch_threshold` | 1.20 | Recovery engine flags quarters requiring >120% of original target |

---

### System

| Config Key | Value | Effect |
|------------|-------|--------|
| `system.tolerance` | 0.001 | Share sum validation tolerance |
| `system.revenue_tolerance` | 0.01 | Revenue identity check tolerance (1%) |
| `system.solver` | method="SLSQP", max_iterations=1000, convergence_tolerance=1e-8 | Solver configuration |
| `system.supersized_deal_threshold` | 3.0 | Flag row if revenue > 3× expected |
| `system.low_confidence_threshold` | 20.0 | Validation fails if >20% of bookings from low-confidence segments |

---

## D. File-by-File Mathematical Breakdown

---

### D1. `data_loader.py` — Data Preparation

**Role**: Transform raw actuals into analysis-ready data; compute baseline economics per segment.

**Inputs**: Raw CSV with columns [Product, Channel, Month, ASP, CW rate, Revenue, SAOs, ...]

**Key Operations**:
- **Column filtering**: Keep only enabled dimension columns + metric columns
- **Confidence scoring**: For each segment (product × channel), count rows. ≥6 = high, ≥3 = medium, <3 = low
- **Fallback imputation**: For low-confidence segments with missing/zero metrics: replace with `global_average × 0.80`
- **Supersized deal detection**: Flag rows where `revenue / (SAOs × ASP × CW_rate) > 3.0`
- **Baseline computation** (`compute_segment_baselines`): Group by active dimensions, aggregate ASP and CW_rate using configured method (median/mean/mode) across all months → produces one {asp, win_rate} pair per segment.

**Output**: `baselines` dict: `{"CM.Marketing": {"asp": 5000, "win_rate": 0.35}, "EOR.Marketing": {"asp": 10000, "win_rate": 0.65}, ...}`

**Formulas**:
```
baseline_asp[segment]      = median(ASP values for that segment across all months)
baseline_win_rate[segment]  = median(CW_rate values for that segment across all months)
```

---

### D2. `target_generator.py` — Monthly Target Distribution

**Role**: Convert annual target to 12 monthly targets using seasonality weights.

**Core Formulas**:
```
If target_source = "growth":
    T_annual = prior_year_actuals × (1 + growth_rate) = $125M × 1.5 = $187,500,000

If target_source = "fixed":
    T_annual = annual_target = $188,000,000

Monthly target:
    T_month_m = T_annual × w_m  (where w_m is the seasonality weight for month m)

Weight normalization:
    w_m = raw_weight_m / Σ(raw_weights)  (ensures sum = 1.0 exactly)
```

**Planning mode adjustments**:
- `rolling_forward`: `T_remaining = T_annual - Σ(actuals_locked)`, redistribute `T_remaining` across unlocked months proportionally: `T_unlocked_m = T_base_m × (T_remaining / Σ T_base_unlocked)`
- `manual_lock`: Same logic but locked months are config-specified, not driven by actuals

**Output**: DataFrame with columns [month, target_revenue], 12 rows.

---

### D3. `ae_capacity.py` — Workforce Capacity Model

**Role**: Compute effective SAO capacity per month.

**Key Variables per Month m**:

| Variable | Definition |
|----------|------------|
| `tenured_hc[m]` | Fully-ramped AEs (starts at 100, reduced by attrition each month) |
| `hc_ramping[m]` | Weighted count of AEs still in ramp period |
| `mentoring_tax[m]` | Fraction of tenured capacity consumed by mentoring |
| `shrinkage_rate[m]` | Fraction of time not spent selling |
| `effective_capacity_saos[m]` | Total SAOs the team can deliver |

**Formulas**:
```
1. Attrition:
   tenured_hc[m] = tenured_hc[m-1] × (1 - annual_attrition / 12)
                 = × (1 - 0.10/12) = × 0.99167

2. Ramp (per tranche):
   months_in_ramp = m - start_month
   days_in = months_in_ramp × 30
   ramp_factor = min(1.0, days_in / duration_days)
   If ramp_factor = 1.0, the tranche is considered fully ramped.

3. Mentoring overhead (only while ramp_factor < 1.0):
   overhead = count × overhead_pct × (1 - ramp_factor)
   Total mentoring overhead (AE-equivalents) capped by max_mentees_per_ae × tenured_hc
   mentoring_tax = total_overhead / tenured_hc, clamped to [0, 1]

4. Shrinkage:
   shrinkage = pto_pct + admin_pct + enablement_pct
   With enablement_scaling = "fixed": enablement_pct = enablement_base_pct = 0.03
   Total: 0.08 + 0.05 + 0.03 = 0.16

5. Tenured capacity:
   C_tenured = tenured_hc × (1 - shrinkage - mentoring_tax) × productivity_per_ae

6. Ramping capacity:
   C_ramping = Σ_tranches(count × ramp_factor × (1 - shrinkage) × productivity_per_ae)

7. Total:
   effective_capacity_saos[m] = max(0, C_tenured) + C_ramping
```

**Output**: DataFrame [month, hc_tenured, hc_ramping, hc_total, mentoring_tax, shrinkage_rate, effective_capacity_saos, capacity_flag]

---

### D4. `economics_engine.py` — Marginal Economics & Cash Cycle

**Role**: Provide effective ASP, win rate, and ROI at any volume level, incorporating decay and cash cycle delays.

**Core Decay Formulas**:
```
Exponential (default for ASP):
    ASP_eff = ASP_base × exp(-rate × max(0, volume - threshold))
    Floored at ASP_base × floor_multiplier

Linear (default for win rate):
    CW_eff = CW_base - rate × max(0, volume - threshold)
    Floored at CW_base × floor_multiplier

Step:
    value = base if volume ≤ threshold, else base × (1 - rate)
    Floored

None:
    value = base (no decay)

ROI per SAO:
    ROI(segment, volume) = ASP_eff(volume) × CW_eff(volume)
```

**Cash Cycle**:
```
in_window_factor(product, month) = Σ { probability | month + delay ≤ 12 }

Example: EOR in month 11
    Delays: {0:0.10, 1:0.30, 2:0.40, 3:0.20}
    Booking months: 11, 12, 13, 14
    In-window: months 11 (0.10) + 12 (0.30) = 0.40

deferred_factor = 1.0 - in_window_factor
```

The optimizer multiplies marginal ROI by `in_window_factor` when deciding where to allocate, steering late-month SAOs toward shorter-cycle products.

**Calibration** (`CalibrationEngine`): Can fit decay curves from deal-level data using `scipy.optimize.curve_fit`. Not used in the default pipeline (`use_calibration = false`).

---

### D5. `optimizer.py` — Core Allocation Engine

**Role**: Solve the constrained allocation problem for each month.

**Decision Variables**: `s = [s_1, s_2, ..., s_9]` where `s_i` = share of total SAOs allocated to segment i.

**Objective**: Maximize `weighted_ROI = Σ_i(s_i × ROI_i(v_i))` where `v_i = s_i × total_SAOs` and `total_SAOs = T_month / weighted_ROI`.

This is a **circular dependency** (ROI depends on volume, volume depends on total SAOs, total SAOs depends on ROI). Solved by **iterating to convergence** (5 iterations, converges in 2-3).

**Constraints**:
```
s_i ≥ share_floor (0.03)    for all i
s_i ≤ share_ceiling (0.40)  for all i
Σ s_i = 1.0
total_SAOs ≤ effective_capacity_saos[m]  (if capacity available)
```

**Greedy Mode (step-by-step)**:
1. Initialize all segments at `share_floor = 0.03`. Remaining share = `1.0 - 0.03 × 9 = 0.73`.
2. In 1% increments: compute marginal ROI for each segment at current volume. If cash cycle enabled, weight by `in_window_factor`. Allocate step to segment with highest marginal ROI that hasn't hit ceiling.
3. Repeat until remaining share < 0.5% or all segments at ceiling.

**Solver Mode (SLSQP)**:
1. Warm-start from greedy solution.
2. Objective: minimize `-weighted_ROI` (maximization via negation).
3. Bounds: `[share_floor, share_ceiling]` per segment.
4. Equality constraint: `Σ s_i = 1.0`.
5. Inequality constraint: `capacity_limit - total_SAOs ≥ 0`.
6. Solver: `scipy.optimize.minimize(method='SLSQP', maxiter=1000, ftol=1e-8)`.

**Per-Segment Output Calculations**:
```
required_saos_i       = s_i × total_SAOs
projected_pipeline_i  = required_saos_i × ASP_eff_i
projected_bookings_i  = required_saos_i × ASP_eff_i × CW_eff_i
projected_deals_i     = round(projected_bookings_i / ASP_eff_i)
in_window_bookings_i  = projected_bookings_i × in_window_factor
deferred_bookings_i   = projected_bookings_i × (1 - in_window_factor)
```

**Capacity Constraint Handling**: If `total_SAOs > capacity_limit`, set `capacity_flag = 1` and cap `total_SAOs = capacity_limit`. This means the month **will miss its target**.

**Supersized Deal Handling**: If segment is flagged supersized, `effective_asp` is capped at `base_asp` (prevents inflated historical ASP from distorting ROI).

---

### D6. `validation.py` — Mathematical Consistency Checks

**Role**: Verify the plan is internally consistent.

**Checks performed**:

| # | Check | Criterion |
|---|-------|-----------|
| 1 | **Revenue Identity** | For every row, `\|projected_bookings - (required_saos × effective_asp × effective_cw_rate)\| / expected ≤ 1%` |
| 2 | **Share Constraints** | `share_floor - tolerance ≤ share ≤ share_ceiling + tolerance` for all rows |
| 3 | **Share Sum** | `\|Σ shares_per_period - 1.0\| ≤ 0.001` for every month |
| 4 | **Capacity** | `Σ required_saos_per_period ≤ effective_capacity_saos` for every month |
| 5 | **Target Alignment** | `\|Σ projected_bookings - Σ target_revenue\| / Σ target_revenue ≤ 0.1%` |
| 6 | **No Negatives** | No negative values in SAOs, pipeline, bookings, share |
| 7 | **Confidence Coverage** | `% of bookings from low-confidence segments ≤ 20%` |
| 8 | **In-Window Target Alignment** | `(target - in_window_bookings) / target ≤ 1%` (cash cycle) |

---

### D7. `recovery.py` — Quarterly Shortfall Redistribution

**Role**: Model recovery when quarters miss targets.

**Core Logic**:
```
1. Aggregate to quarterly grain:
   quarter = (month - 1) // 3 + 1

2. Per-quarter gap:
   gap_q = target_q - projected_q

3. Total shortfall:
   total_shortfall = max(0, Σ target - Σ projected)

4. Find first quarter with a miss.

5. Redistribute shortfall across remaining quarters:
   If capacity data available:
       adjustment_q = shortfall × (capacity_q / Σ remaining_capacity)
   Otherwise: equal split

6. Stretch check:
   stretch_ratio_q = adjusted_target_q / original_target_q
   Flag if > 1.20

7. Recovery quarter:
   First quarter where cumulative_projected ≥ cumulative_target
```

---

## E. Formula Flow (Stepwise, Inputs to Outputs)

---

#### Step 1 — Annual Target

```
T_annual = $125M × (1 + 0.50) = $187,500,000
```

(File: `target_generator.py`)

---

#### Step 2 — Monthly Targets

```
T_m = T_annual × w_m    for m = 1..12

Example: month 4 (peak):
    T_4 = $187.5M × 0.095 = $17,812,500
```

(File: `target_generator.py`)

---

#### Step 3 — Baseline Economics per Segment

```
ASP_base[seg] = median(ASP values for seg across months in actuals)
CW_base[seg]  = median(CW_rate values for seg across months in actuals)

Example: EOR.Marketing → ASP = $10,000, CW = 0.65 → base ROI = $6,500/SAO
```

(File: `data_loader.py`)

---

#### Step 4 — AE Capacity per Month

```
tenured_hc[m] = tenured_hc[m-1] × 0.99167
C_tenured[m]  = tenured_hc[m] × (1 - 0.16 - mentoring_tax[m]) × 45
C_ramping[m]  = Σ(tranche_count × ramp_factor × 0.84 × 45)
capacity[m]   = C_tenured[m] + C_ramping[m]
```

(File: `ae_capacity.py`)

---

#### Step 5 — Effective Economics at Volume

```
ASP_eff(seg, v) = ASP_base × exp(-0.001 × max(0, v - 340))
                  floored at 0.75 × ASP_base

CW_eff(seg, v)  = CW_base - 0.005 × max(0, v - 260)
                  floored at 0.80 × CW_base

ROI(seg, v)     = ASP_eff × CW_eff
```

(File: `economics_engine.py`)

---

#### Step 6 — Cash Cycle In-Window Factor

```
iwf(product, month)      = Σ { prob_delay | month + delay ≤ 12 }
ROI_weighted(seg, v, m)  = ROI(seg, v) × iwf(product, m)
```

(File: `economics_engine.py`, used in `optimizer.py`)

---

#### Step 7 — Share Allocation (per month)

```
Optimize: max Σ(s_i × ROI_weighted_i)
    subject to s_i ∈ [0.03, 0.40], Σ s_i = 1.0

Convergence loop:
    weighted_ROI → total_SAOs = T_m / weighted_ROI
    → volumes = s_i × total_SAOs → ROI_i(v_i) → new weighted_ROI
```

(File: `optimizer.py`)

---

#### Step 8 — Per-Segment Metrics

```
required_saos_i       = s_i × total_SAOs
projected_pipeline_i  = required_saos_i × ASP_eff_i
projected_bookings_i  = required_saos_i × ASP_eff_i × CW_eff_i
in_window_bookings_i  = projected_bookings_i × iwf_i
```

(File: `optimizer.py`)

---

#### Step 9 — Capacity Enforcement

```
If Σ required_saos > capacity[m]:
    cap at capacity, capacity_flag = 1, bookings will miss target.
```

(File: `optimizer.py`)

---

#### Step 10 — Validation

```
Verify:
    bookings ≈ SAOs × ASP × CW  (±1%)
    shares sum to 1.0            (±0.001)
    no negatives
    capacity respected
```

(File: `validation.py`)

---

#### Step 11 — Recovery Analysis

```
Quarterly:
    gap_q = target_q - projected_q
    Redistribute shortfall weighted by capacity.
    Flag stretch > 120%.
```

(File: `recovery.py`)

---

## F. Variable Lineage Map

### Config-Derived Variables

| Variable | Type | Source → Destination |
|----------|------|----------------------|
| `annual_target` | scalar, $ | config → target_generator |
| `seasonality_weights` | dict, 12 floats summing to 1.0 | config → target_generator |
| `share_floor`, `share_ceiling` | scalars, fractions | config → optimizer constraints |
| `decay_params` | nested dict per metric | config → economics_engine |
| `hiring_plan` | list of {count, start_month} | config → ae_capacity |
| `cash_cycle_distributions` | dict per product of {delay: probability} | config → economics_engine |

---

### Data-Derived Variables

| Variable | Type | Definition |
|----------|------|------------|
| `df_clean` | DataFrame, ~108-432 rows | Raw actuals filtered to active dimensions, confidence-scored |
| `baselines` | dict of {segment: {asp, win_rate}} | Median of actuals per segment → economics_engine |
| `confidence_level` | categorical: high/medium/low per row | From row counts per segment |

---

### Generated Variables (Pipeline)

| Variable | Type | Consumers |
|----------|------|-----------|
| `targets` | DataFrame, 12 rows — [month, target_revenue] | optimizer, validation, recovery |
| `capacity` | DataFrame, 12 rows — [month, hc_tenured, hc_ramping, effective_capacity_saos, ...] | optimizer, validation, recovery |
| `results` | DataFrame, ~108 rows — [month, segment_key, share, required_saos, effective_asp, effective_cw_rate, projected_pipeline, projected_bookings, in_window_bookings, deferred_bookings, ...] | validation, recovery, version_store |
| `opt_summary` | dict — {total_annual_bookings, total_annual_saos, segment_summary, ...} | version_store |
| `validation` | dict — {passed: bool, checks: [...]} | version_store |
| `recovery_analysis` | dict — {quarterly_summary, recovery_plan, stretch_flags, risk_assessment} | version_store |

---

### Key Intermediate Variables (within optimizer)

| Variable | Type | Definition |
|----------|------|------------|
| `shares` | dict {segment_key: float} | Current allocation, updated each greedy step |
| `weighted_roi` | scalar, $/SAO | `Σ(s_i × ROI_i(v_i))`, iteratively converged |
| `total_saos` | scalar | `T_month / weighted_roi`, iteratively converged |
| `marginal_roi` | per segment, $/SAO | ROI at current volume × in_window_factor; used to pick best segment for next allocation step |

---

## G. Optimization Model

### Decision Variables

`s = [s_1, ..., s_9]` — share of total monthly SAOs allocated to each of 9 segments (product × channel)

---

### Objective Function

```
maximize weighted_ROI(s) = Σ_i { s_i × ASP_eff(seg_i, s_i × T/wROI)
                                     × CW_eff(seg_i, s_i × T/wROI)
                                     × iwf(product_i, month) }
```

Note: This is effectively **maximize bookings per SAO, weighted by in-window realization probability**.

---

### Constraints

```
s_i ≥ 0.03    for all i = 1..9       (share floor)
s_i ≤ 0.40    for all i = 1..9       (share ceiling)
Σ s_i = 1.0                           (full allocation)
T_month / weighted_ROI(s) ≤ capacity_month   (SAO capacity limit)
```

---

### Penalties / Implicit

- Decay functions serve as implicit "diminishing returns" penalties — pushing more volume into a segment reduces its marginal ROI
- Cash cycle in-window factor serves as an implicit penalty on long-cycle products in late months
- No explicit penalty terms in the objective function

---

### Solver / Solution Method

| Method | Description |
|--------|-------------|
| **Greedy** | Deterministic, iterative 1% step allocation. O(n × steps) per month. Not globally optimal but respects diminishing returns at each step. |
| **SLSQP** (`scipy.optimize.minimize`) | Sequential Least Squares Programming. Handles nonlinear objectives and constraints. Warm-started from greedy solution. Converges to local optimum (which is likely global given the concavity of decaying ROI functions). |

### Multiple Optimization Stages

The optimization runs **independently per month** (12 separate optimization problems). There is no cross-month optimization — each month's allocation is determined solely by that month's target, capacity, and economics.

---

## H. Aggregations and Transformations

---

#### Baseline Computation (`data_loader`)

| Attribute | Detail |
|-----------|--------|
| **What** | ASP and CW rate values per segment |
| **Dimension** | Grouped by product × channel (active dimensions) |
| **Aggregation** | Median across all months (collapses time dimension) |
| **Purpose** | Establish "normal" economics for each segment before decay is applied |
| **Affects optimization** | Yes — determines base ROI for each segment |

---

#### Monthly Waterfall (`run_plan.py`)

| Attribute | Detail |
|-----------|--------|
| **What** | Consolidated month-by-month view merging targets, capacity, and allocation |
| **Dimension** | Grouped by month |
| **Aggregation** | Sum of required_saos, projected_pipeline, projected_bookings across segments |
| **Derived columns** | `capacity_gap = capacity - demand`, `bookings_vs_target = bookings - target`, cumulative sums |
| **Purpose** | Reporting only — does not affect optimization |

---

#### Cash Cycle Waterfall (`run_plan.py`)

| Attribute | Detail |
|-----------|--------|
| **What** | Detailed booking realization schedule showing when SAOs convert |
| **Dimension** | Per segment per month, expanded by delay probabilities |
| **Purpose** | Visibility into deferred bookings — does not feed back into optimization |

---

#### Quarterly Aggregation (`recovery.py`)

| Attribute | Detail |
|-----------|--------|
| **What** | Monthly results aggregated to quarters |
| **Dimension** | `quarter = (month - 1) // 3 + 1` |
| **Aggregation** | Sum of projected_bookings and target_bookings per quarter |
| **Purpose** | Drives recovery redistribution and stretch analysis |

---

#### Optimization Summary (`optimizer.py`)

| Attribute | Detail |
|-----------|--------|
| **What** | Annual totals and per-segment breakdowns |
| **Aggregation** | Sum across all months; per-segment: sum of bookings and SAOs, mean of share |
| **Derived** | `average_weighted_roi = total_bookings / total_saos` (bookings-weighted, not simple mean) |
| **Purpose** | Top-level KPIs for version comparison |

---

#### HHI Concentration (`comparator.py`)

| Attribute | Detail |
|-----------|--------|
| **What** | Herfindahl-Hirschman Index |
| **Formula** | `HHI = Σ(normalized_share_i²)` where shares are annual averages |
| **Purpose** | Measures allocation concentration risk. HHI = 1/9 ≈ 0.111 (perfectly equal) to 1.0 (one segment gets everything) |

---

#### Volatility Metrics (`comparator.py`)

| Attribute | Detail |
|-----------|--------|
| **What** | Standard deviation, coefficient of variation, max/min ratio of monthly bookings |
| **Purpose** | Measures plan predictability. Lower CV = smoother targets for sales teams |

---

## I. Open Questions / Ambiguities

---

#### 1. Circular ROI Convergence

The optimizer's `_compute_weighted_roi` iterates 5 times with a 0.1% convergence check. The initial SAO estimate is `target_revenue / 1000` (a rough heuristic). This converges well in practice but is not guaranteed for extreme decay parameters.

---

#### 2. Greedy vs. Solver Divergence

The greedy mode is the warm-start for the solver. If the solver doesn't converge, it falls back to the greedy solution. No explicit logging of how far apart the two solutions are.

---

#### 3. Decay Parameters Are Global by Default

All 9 segments share the same ASP decay (exponential, rate=0.001, threshold=340) and CW decay (linear, rate=0.005, threshold=260). Per-segment overrides exist in config but are commented out. This means CM.Partner (small volume) and EOR.Marketing (large volume) face the same decay thresholds, which is likely unrealistic.

---

#### 4. No Cross-Month Optimization

Each month is optimized independently. There is no mechanism to "borrow" capacity from a low-target month to help a high-target month, nor to shift SAOs earlier to benefit from cash cycle realization.

---

#### 5. Ramp Factor on Start Month

When `month == start_month`, `months_in_ramp = 0`, so `days_in = 0` and `ramp_factor = 0`. Hires contribute zero capacity in their start month. This is a modeling choice (they're onboarding), but it means month-1 hires (25 AEs) contribute nothing in January.

---

#### 6. Attrition Applied Before Mentoring

Tenured HC is reduced by attrition, then mentoring tax is computed on the reduced pool. This means attrition slightly reduces the mentoring capacity ceiling.

---

#### 7. Month 11 and 12 Allocation Shift

In v012 results, months 11-12 show dramatically different share patterns (EOR.Marketing drops from ~40% to 3% in month 12, Payroll.Marketing jumps to 40%). This is the cash cycle steering effect — with only 1 month left in the horizon, long-cycle products have very low in-window factors, so the optimizer reallocates to shorter-cycle products (Payroll closes faster).

---

#### 8. Enablement Scaling

The config says `enablement_scaling: "fixed"` but the code supports `"proportional"` mode where enablement increases with new-hire ratio. The proportional formula uses `num_tranches / total_tranches_ever` as a rough proxy, which is a coarse approximation.

---

#### 9. Supersized Deal Revenue Column

The raw data has rows with very high `2025 Revenue` (e.g., CM.Outbound month 11 = $4.3M vs calculated = $401K). These are flagged as supersized in the data loader, and the optimizer caps their ASP at base. However, the raw Revenue column seems inconsistent with SAOs × ASP × CW in several rows — suggesting the raw data may contain actual bookings that differ from the formula-derived values.

---

#### 10. Modules Not in Pipeline

`adjustments.py`, `comparator.py`, and `what_if.py` are fully implemented but not called by `run_plan.py`. Their mathematical logic (mid-cycle re-planning, scenario perturbations, multi-version comparison) is self-contained and would be invoked by a separate orchestrator or interactive session.

---

#### 11. Hard-Coded Step Size

The greedy optimizer uses a fixed `step_size = 0.01` (1% per step). This is not configurable. With 9 segments and 0.73 remaining share, this means ~73 steps per month, which is adequate for convergence but may be too coarse for fine-grained allocation near boundaries.

---

#### 12. Capacity Flag Is Binary

When demand exceeds capacity, `capacity_flag = 1` for ALL segments in that month (not just the marginal one). The total SAOs are capped but the share distribution is preserved, meaning the shortfall is spread proportionally.
