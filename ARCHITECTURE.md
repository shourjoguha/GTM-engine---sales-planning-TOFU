# GTM Planning Engine — Architecture Specification

## Related Documentation

This document is one of three complementary references:

| Document | Purpose | Audience | When to Use |
|-----------|---------|-----------|--------------|
| **ARCHITECTURE.md** (this file) | System blueprint and technical specification | Engineers, architects, implementation team | "What do I build?" - Module specs, data flow, file structure, build phases |
| **Mathematical Reverse-Engineering.md** | Complete mathematical foundations and formula derivations | Data scientists, analysts, validators | "How does the math work?" - Formulas, variable lineage, optimization model, validation calculations |
| **Open Questions & Forecasting Engine.md** | Strategic roadmap and parameter resolution guidance | Architects, researchers, leadership | "How do we evolve?" - Parameter validation, forecasting architecture, implementation roadmap |

**Key relationships:**
- This document provides the structural blueprint for building the system
- Mathematical Reverse-Engineering provides the mathematical reference for understanding and validating all calculations
- Open Questions & Forecasting Engine provides the research roadmap for evolving from deterministic to probabilistic planning

---

## Document Purpose

This is the technical specification for a config-driven, modular GTM (Go-To-Market) planning engine. The system allocates sales capacity across channels, products, and segments to meet revenue targets — accounting for AE hiring plans, ramp dynamics, marginal economics, and mid-cycle adjustments.

Built for continuous use: annual/quarterly planning cycles AND mid-quarter re-planning when reality changes.

---

## 1. Definitions & Glossary

### 1.1 Business Terms

| Term | Definition |
|------|-----------|
| **SAO** | Sales Accepted Opportunity. A qualified lead that has been accepted by a sales rep for active pursuit. The primary unit of "demand" in this system. |
| **ASP** | Average Selling Price. The average revenue per closed deal for a given segment. Can be mean or median depending on config. |
| **CW Rate** | Close-Win Rate. The percentage of SAOs that convert to closed-won deals. Varies by product, channel, AE tenure, and volume. |
| **ROI (Efficiency)** | Revenue generated per SAO = ASP × CW Rate. Used to rank segments for allocation priority. |
| **Pipeline** | Total potential revenue from all active opportunities = SAOs × ASP. Represents the "top of funnel" value before conversion. |
| **Bookings** | Confirmed revenue from closed-won deals = SAOs × ASP × CW Rate. The actual revenue the business counts. |
| **AE** | Account Executive. The sales reps who work SAOs to close deals. |
| **TOFU** | Top of Funnel. The lead generation and qualification stages (Marketing, Outbound, Partner) that feed SAOs to AEs. |
| **EOR** | Employer of Record. One of Remote's core products — managing international employees on behalf of clients. Highest ASP range ($10K–$15K). |
| **CM** | Contractor Management. Another Remote product — managing international contractors. Lower ASP range ($5K–$8K). |
| **Payroll** | Remote's payroll management product — handling international payroll for client employees. Highest ASP range ($12K–$20K), lower volume. |
| **Territory** | A defined segment of the market assigned to specific AEs. Can be geographic, product-based, or account-based. |

### 1.2 System Variables

| Variable | Symbol | Unit | Definition |
|----------|--------|------|-----------|
| **Annual Target** | `T_annual` | $ | The total revenue (bookings) the sales org must deliver in the fiscal year. |
| **Growth Rate** | `g` | % | Year-over-year growth rate applied to derive `T_annual` from prior year actuals. |
| **Seasonality Weights** | `w_m` | ratio | Per-month (or per-quarter) weight determining what share of annual target falls in each period. Must sum to 1.0. |
| **Period Target** | `T_p` | $ | Target for a specific period (month or quarter) = `T_annual × w_m`. |
| **Channel Share** | `s_c` | ratio | The fraction of total SAOs allocated to a specific product-channel segment. All shares sum to 1.0 per period. |
| **Share Floor** | `s_min` | ratio | Minimum share any segment must receive (default: 0.05). Prevents zero-coverage. **Manually set in config** — the engine enforces this as a hard constraint, it does not calculate it. See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for data-driven resolution approaches. |
| **Share Ceiling** | `s_max` | ratio | Maximum share any segment can receive (default: 0.40). Prevents over-concentration. **Manually set in config** — same as floor, this is a human judgment call enforced by the optimizer. See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for data-driven resolution approaches. |
| **Stretch Threshold** | `stretch_max` | ratio | Maximum ratio of re-planned target to original target for any quarter (default: 1.20). If recovery would require a quarter to exceed this, the system flags it as a risk. |
| **Effective ROI** | `ROI_eff(v)` | $/SAO | ROI at volume level `v`, after applying decay. `ROI_eff(v) = ASP(v) × CW(v)`. |
| **ASP Decay Rate** | `d_asp` | ratio/unit | Rate at which ASP degrades as volume increases. Reflects pricing pressure at scale. **Configured independently from win rate decay.** Configurable per segment with global default. See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for scientific resolution approaches to decay parameter estimation.
| **Win Rate Decay Rate** | `d_cw` | ratio/unit | Rate at which CW Rate degrades as volume increases. Reflects lead quality degradation at scale. **Configured independently from ASP decay.** Configurable per segment with global default. See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for scientific resolution approaches to decay parameter estimation. |
| **ASP Decay Threshold** | `v_thresh_asp` | SAOs | Volume level at which ASP decay begins. Below this, ASP is constant at its base value. |
| **Win Rate Decay Threshold** | `v_thresh_cw` | SAOs | Volume level at which CW Rate decay begins. Below this, CW rate is constant at its base value. |
| **Decay Floor** | `floor_mult` | ratio | Minimum value as a fraction of the base (e.g., 0.70 = ASP won't drop below 70% of base). Prevents decay from driving values to zero. **Set independently for ASP and CW Rate.** |
| **Confidence Level** | `conf` | categorical | Low / Medium / High. Derived from data density for a segment. Low = fewer than N deals, uses fallback values. |
| **Confidence Threshold** | `N_conf` | count | Minimum number of historical deals required for a segment to be rated "high confidence" (default: 30). See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for margin-of-error-based threshold calculations.
| **Fallback Multiplier** | `f_mult` | ratio | Applied to parent segment's values when a sub-segment has low confidence (e.g., 0.7x). |

### 1.3 AE Capacity Variables

| Variable | Symbol | Unit | Definition |
|----------|--------|------|-----------|
| **AE Headcount (Tenured)** | `HC_tenured` | count | Number of fully-ramped AEs at the start of the period. |
| **Hiring Tranche** | `(n, t)` | (count, month) | A batch of `n` new AEs starting in month `t`. Multiple tranches form the hiring plan. |
| **Ramp Duration** | `Y` | days | Time for a new AE to reach full productivity from start date. |
| **Ramp Velocity** | `X` | % per period | Rate at which new AEs gain productivity. Linear ramp: productivity at day `d` = `min(d/Y, 1.0)`. |
| **Mentoring Overhead** | `A` | % per new hire | Percentage of a tenured AE's time consumed per new hire they mentor. Degrades linearly from `A%` to `0%` over `Y` days. |
| **Total Mentoring Tax** | `M_tax` | ratio | Combined mentoring overhead on tenured AE pool = `Σ(count × A × (1 - days_in/Y))` for all ramping AEs, capped at `max_mentees_per_ae × tenured_hc`, then divided by `tenured_hc` and clamped to `[0, 1]`. See [Mathematical Reverse-Engineering](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine%20%E2%80%94%20Mathematical%20Reverse-Engineering.md) for complete derivation. |
| **PTO Rate** | `pto` | % | Percentage of AE time lost to paid time off (static, annual). |
| **Admin Rate** | `admin` | % | Percentage of AE time lost to admin tasks (static). |
| **Enablement Rate** | `enable(r)` | % | Percentage of time for training. Function of new-hire ratio `r = new_hires / total_HC`. Higher when many new hires are ramping. |
| **Attrition Rate** | `attrition` | % annual | Expected annual AE attrition. Applied monthly as `attrition/12`. |
| **Backfill Delay** | `backfill_months` | months | Time between an AE departing and their backfill starting. |
| **Effective Capacity** | `C_eff(t)` | SAOs/month | Total SAOs the AE team can deliver in month `t` = `(tenured_AEs × (1 - shrinkage - M_tax) × productivity_per_AE) + (ramping_AEs × ramp_factor × (1 - shrinkage) × productivity_per_AE)`. |
| **Productivity per AE** | `P_ae` | SAOs/month | Baseline SAOs a fully-ramped AE can work per month. Derived from historical data or set in config. See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for CRM-based empirical derivation approaches. |

### 1.4 Planning Mode Variables

| Variable | Values | Definition |
|----------|--------|-----------|
| **Planning Mode** | `full_year`, `rolling_forward`, `manual_lock` | Controls how the optimizer treats completed periods. |
| **Lock Mask** | list of periods | In `manual_lock` mode, which periods are frozen. The optimizer only adjusts unlocked periods. |
| **Actuals** | dataframe | Real performance data for completed periods. Replaces plan data in `rolling_forward` mode. |
| **Remaining Target** | $ | In `rolling_forward`: `T_annual - Σ(actuals for locked periods)`. The optimizer distributes this across unlocked periods. |

---

## 2. Module Architecture

### 2.1 Module Overview

**Pipeline vs. Support Modules:**

The 13 modules are organized into two categories:

| Category | Modules | Purpose |
|-----------|----------|---------|
| **Pipeline Modules** (8) | Config Manager, Data Loader, Target Generator, Marginal Economics, AE Capacity, Allocation Optimizer, Validation Engine, Recovery & Rebalancing | Core execution flow invoked by `run_plan.py` to generate allocation results |
| **Support Modules** (5) | Version Store, Version Comparator, What-If Engine, Ad-Hoc Adjustment, Lever Analysis Engine | Complementary functionality for versioning, comparison, scenario modeling, mid-cycle re-planning, and gap attribution |

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FOUNDATION LAYER                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Config       │  │ Data         │  │ Version                  │  │
│  │ Manager      │  │ Loader       │  │ Store                    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────────────┘  │
│         │                 │                                         │
├─────────┼─────────────────┼─────────────────────────────────────────┤
│         │    MODELLING LAYER                                        │
│         ▼                 ▼                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Target       │  │ Marginal     │  │ AE Capacity              │  │
│  │ Generator    │  │ Economics    │  │ Model                    │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘  │
│         │                 │                        │                │
│         └────────┬────────┘                        │                │
│                  ▼                                  │                │
│         ┌──────────────────┐                       │                │
│         │ Allocation       │◄──────────────────────┘                │
│         │ Optimizer        │  (supply constraint)                   │
│         └────────┬─────────┘                                        │
│                  │                                                   │
├──────────────────┼──────────────────────────────────────────────────┤
│                  │    RECONCILIATION LAYER                           │
│                  ▼                                                   │
│  ┌──────────────────┐  ┌──────────────┐  ┌─────────────────────┐   │
│  │ Recovery &       │  │ Validation   │  │ Ad-Hoc              │   │
│  │ Rebalancing      │  │ Engine       │  │ Adjustment          │   │
│  └──────────────────┘  └──────────────┘  └─────────────────────┘   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                        ANALYSIS LAYER                               │
│  ┌──────────────────┐  ┌───────────────┐  ┌───────────────────┐   │
│  │ What-If          │  │ Version       │  │ Lever Analysis    │   │
│  │ Engine           │  │ Comparator    │  │ Engine            │   │
│  └──────────────────┘  └───────────────┘  └───────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Module Specifications

---

#### Module 1: Config Manager (`config_manager.py`)

**Purpose**: Load, validate, and provide access to the YAML configuration.

**Inputs**: `config.yaml` file path.

**Outputs**: A validated config object that all other modules query.

**Key responsibilities**:
- Load YAML and validate against expected schema (raise clear errors for missing/invalid fields)
- Resolve dimension toggles: which columns in the data are "active" for this run
- Provide getter methods: `config.get("allocation.floor")`, `config.get("ae_model.ramp_duration_days")`
- Support config overrides (for what-if scenarios that perturb specific values)

---

#### Module 2: Data Loader (`data_loader.py`)

**Purpose**: Ingest raw data, apply dimension toggles, score confidence, and produce a clean analysis-ready dataframe.

**Inputs**: Raw data file (CSV/Excel), config (for active dimensions, confidence threshold, fallback rules).

**Outputs**: Clean dataframe with columns for all active dimensions, metrics (SAOs, Revenue, ASP, CW Rate), and a `confidence_level` column.

**Key responsibilities**:
- Read data from CSV or Excel (sheet name configurable)
- Filter to active dimensions only (drop toggled-off columns)
- Compute `confidence_level` per segment:
  - Count historical deals per segment
  - If count < `N_conf`: mark "low", apply fallback multiplier from parent segment
  - If count >= `N_conf` and < `2 × N_conf`: mark "medium"
  - Else: mark "high"
- Apply fallback hierarchy for sparse segments: sub-segment → segment → product → global
- Detect and flag supersized deals (where actual revenue >> SAO count × ASP, beyond a configurable threshold)
- Output: `df_clean` with standardised column names

---

#### Module 3: Target Generator (`target_generator.py`)

**Purpose**: Distribute the annual revenue target across planning periods.

**Inputs**: Config (annual target, growth rate, planning mode, seasonality weights, peak months), actuals (if rolling_forward).

**Outputs**: A dataframe with one row per planning period and the target for that period.

**Key responsibilities**:
- Calculate `T_annual` from prior year actuals × `(1 + g)`, or accept a hard-coded target
- Distribute across periods using one of two modes:
  - **Monthly mode**: Apply `w_m` seasonality weights (manually configured in config). Weights must sum to 1.0. See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for scientific resolution approaches to seasonality estimation.
  - **Quarterly mode**: Distribute to quarters using quarterly weights. The optimizer then distributes within quarters.
- In `rolling_forward` mode: replace completed periods with actuals, compute remaining target, redistribute across unlocked periods (maintaining seasonality proportions for unlocked months)
- In `manual_lock` mode: freeze specified periods, redistribute only across unlocked periods

**Calculations**:
```
Monthly target: T_m = T_annual × w_m
Quarterly target: T_q = T_annual × w_q (where w_q = Σ w_m for months in quarter)
Rolling forward remaining: T_remaining = T_annual - Σ(actuals for locked months)
Redistributed: T_m_new = T_remaining × (w_m / Σ w_m for unlocked months)
```

---

#### Module 4: Marginal Economics Engine (`economics_engine.py`)

**Purpose**: Compute the effective ROI (ASP × CW Rate) at any given volume level, accounting for decay/improvement curves.

**Inputs**: Config (decay function type, parameters per segment, calibration toggle), calibration data (optional).

**Outputs**: A function `get_effective_roi(segment, volume)` that returns the ROI at a given volume level.

**Key responsibilities**:
- Support three decay function types (configurable per segment):
  - **Linear**: `ROI(v) = ROI_base - d × max(0, v - v_threshold)`, floored at `ROI_floor`
  - **Exponential**: `ROI(v) = ROI_base × exp(-d × max(0, v - v_threshold))`, floored at `ROI_floor`
  - **Step**: `ROI(v) = ROI_base if v <= v_threshold else ROI_base × (1 - d)`, floored at `ROI_floor`
  - See [Mathematical Reverse-Engineering](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine%20%E2%80%94%20Mathematical%20Reverse-Engineering.md) for complete formula derivations and cash cycle integration.
- Toggle between default parameters (from config) and calibrated parameters (from calibration module)
- The calibration sub-module (`calibration.py`) fits decay curves from historical data:
  - Takes deal-level data, bins by volume level, fits the chosen function type
  - Outputs fitted parameters that replace defaults
- Compute ASP(v) and CW(v) separately — they may decay at different rates
- Grain control: calculate decay at configurable hierarchy level (product-channel, product, channel, or global)

**Note**: On Day 1, use default decay parameters from config. As deal data accumulates, switch to calibrated values.

---

#### Module 5: AE Capacity Model (`ae_capacity.py`)

**Purpose**: Model the effective SAO capacity of the AE team by month, accounting for hiring, ramp, mentoring, and shrinkage.

**Inputs**: Config (hiring plan, ramp parameters, shrinkage rates), current AE roster (or starting HC).

**Outputs**: A dataframe with effective AE capacity (SAOs deliverable) per month.

**Key responsibilities**:
- Process the hiring plan: list of `(count, start_month)` tranches
- For each month, calculate:
  - **Tenured AE pool**: Starting HC + completed ramp from prior tranches - attrition
  - **Ramping AE pool**: New hires currently in ramp period (not yet at full productivity)
  - **Ramp productivity**: For a new AE at day `d` of ramp: `productivity = min(d × X, 1.0)` where X = ramp velocity. Linear ramp reaching 1.0 at `Y` days.
  - **Mentoring tax on tenured AEs**: Each ramping AE consumes `A% × (1 - days_in_ramp/Y)` of ONE tenured AE's time. Total tax = `Σ(A × (1 - d_i/Y))` for all currently ramping AEs. This reduces tenured AE effective capacity.
  - **Shrinkage**: `shrinkage = pto + admin + enable(new_hire_ratio)` where `enable = base_enable × (new_hires / total_HC)`. Applied to both tenured and ramping AEs.
  - **Attrition**: Applied monthly as `attrition_annual / 12`. Reduces tenured pool. Backfill enters as a new tranche after `backfill_delay` months.
- **Effective capacity per month**:
  ```
  C_tenured = max(0, HC_tenured × (1 - shrinkage - M_tax) × P_ae)
  C_ramping = Σ(new_hire × ramp_factor × (1 - shrinkage) × P_ae) for each tranche
  C_eff = C_tenured + C_ramping
  ```
  Note: The `max(0, ...)` clamp prevents negative capacity due to high mentoring tax. See [Mathematical Reverse-Engineering](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine%20%E2%80%94%20Mathematical%20Reverse-Engineering.md) for complete derivation.
- Output includes: HC breakdown (tenured, ramping, total), capacity, mentoring overhead, and flags for months where M_tax exceeds a warning threshold

---

#### Module 6: Allocation Optimizer (`optimizer.py`)

**Purpose**: The core engine. Determines SAO allocation across segments to meet targets, subject to constraints.

**Inputs**: Period targets (from Target Generator), effective ROI curves (from Economics Engine), AE capacity (from Capacity Model), config (objective, constraints, mode).

**Outputs**: SAO allocation by segment by period, with projected pipeline, bookings, and deal counts.

**Two modes**:

##### Greedy Mode (`mode: greedy`)
Enhanced version of the current algorithm. For each period:
1. Assign `s_min` share to every segment
2. Sort segments by effective ROI at their current allocated volume
3. Greedily assign remaining share to highest-ROI segment, up to `s_max`
4. After each allocation step, re-evaluate ROI (accounting for decay at new volume)
5. Calculate: `required_SAOs = T_period / weighted_avg_ROI`
6. Check against AE capacity. If demand > supply, flag gap.

*Pros*: Fast, explainable, easy to walk through in a meeting.
*Cons*: May not find the global optimum when decay curves interact.

##### Solver Mode (`mode: solver`)
Uses `scipy.optimize.minimize` with configurable objective and constraints:
- **Decision variables**: Share allocation vector `s = [s_1, s_2, ..., s_n]` per period
- **Objective function** (configurable):
  - Maximise bookings: `max Σ(s_i × SAOs_total × ASP_i(v_i) × CW_i(v_i))`
  - Maximise pipeline: `max Σ(s_i × SAOs_total × ASP_i(v_i))`
  - Minimise AE HC: `min HC` such that capacity >= demand
- **Constraints**:
  - `s_i >= s_min` for all i (floor)
  - `s_i <= s_max` for all i (ceiling)
  - `Σ s_i = 1.0` (shares sum to 1)
  - `total_SAOs <= C_eff` (capacity constraint)
  - Custom constraints from config (e.g., "Outbound share >= 0.15")
- **Warm start**: Uses greedy solution as starting point for solver

**Outputs per period**:
```
segment | share | required_SAOs | projected_pipeline | projected_bookings | projected_deals
```
See [Mathematical Reverse-Engineering](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine%20%E2%80%94%20Mathematical%20Reverse-Engineering.md) for complete optimization model formulation, convergence algorithm, and output calculation formulas.

---

#### Module 7: Recovery & Rebalancing (`recovery.py`)

**Purpose**: Handle quarterly target misses and model recovery options.

**Inputs**: Quarterly targets, quarterly actuals/projections, AE capacity, config (stretch threshold).

**Outputs**: Recovery plan showing redistribution, stretch flags, and mentoring relief analysis.

**Key responsibilities**:
- Compare quarterly projected bookings (or actuals) to quarterly targets
- If a quarter misses: calculate shortfall
- Redistribute shortfall across remaining quarters, weighted by their relative capacity:
  ```
  Q_i_adjusted = Q_i_original + shortfall × (C_eff_Qi / Σ C_eff_remaining)
  ```
- Flag if any quarter's adjusted target exceeds `stretch_max × Q_original`:
  ```
  If Q_adjusted / Q_original > stretch_max → RISK: "Q3 requires 135% of plan, exceeds 120% threshold"
  ```
- Model mentoring relief: what happens if `A%` is reduced by X%? How much capacity is freed? Does it close the gap? Output the break-even A% value.
- Identify the earliest quarter where cumulative bookings recover to the annual trajectory

---

#### Module 8: Validation Engine (`validation.py`)

**Purpose**: Verify mathematical consistency and constraint satisfaction across all module outputs.

**Inputs**: Allocation results, targets, capacity, config constraints.

**Outputs**: Validation report (pass/fail per check with diagnostics).

**Checks performed**:
1. **Revenue identity**: `bookings = SAOs × ASP × CW_rate` for every segment-period (tolerance: 0.1%)
2. **Share constraint**: `s_min <= share <= s_max` for every segment-period
3. **Share sum**: `Σ shares = 1.0` for every period (tolerance: 0.001)
4. **Capacity check**: `total_SAOs <= C_eff` for every period
5. **Target alignment**: `Σ projected_bookings ≈ T_annual` (tolerance: 1%)
6. **No negative values**: SAOs, revenue, share, HC all >= 0
7. **HC consistency**: AE count in capacity model matches hiring plan trajectory
8. **Stretch check**: No quarter exceeds `stretch_max` (if recovery has been applied)
9. **Confidence coverage**: Percentage of total bookings coming from "low confidence" segments (flag if > 20%)

---

#### Module 9: Ad-Hoc Adjustment (`adjustments.py`)

**Purpose**: Handle mid-cycle re-planning by locking completed periods and re-optimizing.

**Inputs**: Current plan (from Version Store), actuals for completed periods, adjustment parameters, config.

**Outputs**: Updated plan for remaining periods.

**Key responsibilities**:
- Accept actuals data and merge with plan
- Lock completed periods (or manually specified periods)
- Compute remaining target: `T_remaining = T_annual - Σ actuals`
- Re-trigger: Target Generator (rolling_forward) → Optimizer → Recovery → Validation
- Store the re-plan as a new version (preserving the original for comparison)
- Support specific adjustments:
  - HC changes: "AE X left" or "Add 5 AEs in month 8"
  - Target changes: "Annual target revised to $200M"
  - Segment changes: "EOR ASP revised to $12K"

---

#### Module 10: What-If Engine (`what_if.py`)

**Purpose**: Model 2-5 named risk scenarios against the base plan.

**Inputs**: Base plan, what-if scenario definitions (from config), all upstream modules.

**Outputs**: Comparison dataframe showing delta from base for every key metric.

**Key responsibilities**:
- Read what-if scenarios from config (max 5)
- Each scenario is a named bundle of perturbations:
  ```yaml
  - name: "Q2 attrition spike"
    perturbations:
      ae_headcount_change: {month_4: -3, month_5: -2}
      backfill_delay_months: 2
  ```
- For each scenario:
  - Deep-copy the base config
  - Apply perturbations as config overrides
  - Run the full pipeline (Target → Economics → Capacity → Optimizer → Recovery)
  - Store results
- Output comparison: base vs. each scenario across key metrics (bookings, SAOs, HC, capacity utilisation)

---

#### Module 11: Version Store (`version_store.py`)

**Purpose**: Persist plan versions with their configs and results for comparison.

**Inputs**: Config snapshot, allocation results, metadata.

**Outputs**: Versioned records stored as JSON + CSV files.

**Key responsibilities**:
- Save each run as a version with:
  - `version_id`: auto-incrementing integer
  - `timestamp`: when the run was executed
  - `description`: user-provided label (e.g., "Q2 replan after attrition")
  - `planning_mode`: full_year / rolling_forward / manual_lock
  - `config_snapshot`: full YAML config used for this run
  - `config_hash`: SHA256 of config for dedup detection
  - `results`: allocation dataframe as CSV
  - `summary_metrics`: key rollup numbers (total bookings, total SAOs, AE HC, etc.)
- Storage format: `versions/v001/` directory containing `config.yaml`, `results.csv`, `summary.json`
- Load any version by ID for comparison

---

#### Module 12: Version Comparator (`comparator.py`)

**Purpose**: Compare two or more plan versions across multiple analytical dimensions.

**Inputs**: Two or more version IDs.

**Outputs**: Comparison report with numeric diffs, volatility metrics, and risk indicators.

**Metrics compared**:
- **Numeric diffs**: Total bookings, pipeline, SAOs, AE HC, productivity per AE — absolute and percentage
- **Allocation shift**: How did segment shares change between versions?
- **Volatility**: Standard deviation of monthly targets (is one version "lumpier" than another?)
- **Coefficient of Variation**: Monthly target CV = σ/μ (lower = smoother, more predictable for sales teams)
- **Concentration Risk**: Herfindahl-Hirschman Index across segments = `Σ(share_i²)`. Higher = more concentrated. Range [1/n, 1.0].
- **Capacity Utilisation Variance**: How evenly is AE capacity used across the year? Uneven = some months overworked, some idle.
- **Stretch Exposure**: Which version has more quarters near or above the stretch threshold?
- **Confidence-Weighted Risk**: What % of bookings come from low-confidence segments in each version?

---

#### Module 13: Lever Analysis Engine (`lever_analysis.py`)

**Purpose**: When a plan misses its bookings target, decompose the gap into root causes and rank operational levers by their estimated impact using analytical closed-form sensitivity — no pipeline re-runs required.

**Inputs**:
- `base_results` (DataFrame) — segment × month allocation from AllocationOptimizer
- `capacity` (DataFrame) — monthly AE capacity from AECapacityModel
- `targets` (DataFrame) — monthly revenue targets from TargetGenerator
- `baselines` (dict) — `{segment: {asp, win_rate}}` from DataLoader

**Outputs** (saved to version dir via `--mode recommend`):
- `lever_analysis.csv` — Ranked lever impact table (lever, estimated gain, % of gap, recommendation)
- `lever_recommendations.txt` — Plain-language narrative for leadership
- `lever_analysis_report.json` — Summary metrics (gap, gap_pct, annual_target, actual_bookings, sao_shadow_price)

**Key concepts**:
- **Bookings identity**: `bookings_m = Σ_s SAOs_s × ASP_s(vol) × CW_s(vol) × IWF_s`
  Each factor maps directly to a lever category (capacity / ASP decay / win-rate decay / cash cycle).
- **SAO shadow price** π: `bookings_constrained / saos_constrained` — bridges capacity (SAOs) and revenue (bookings) in a single scalar. Only capacity-constrained months contribute; unconstrained months have zero marginal value.
- **Gap decomposition waterfall**: Baseline (no decay, full capacity) → capacity shortfall → ASP decay loss → win-rate decay loss → cash cycle deferral → actual bookings.
- **Analytical sensitivity** `∂bookings/∂lever`: computed from closed-form expressions, not finite differences. O(1), completes in <2 seconds regardless of plan size.
- Lever bounds and step sizes are configured in `config['business_recommendations']['levers']`.

**Invoked by**: `run_plan.py --mode recommend` and also during full mode runs (automatic gap attribution for plans missing target)

---

## 3. Data Flow

### 3.1 Full Planning Run

```
config.yaml ──► Config Manager
                    │
                    ▼
raw_data.csv ──► Data Loader ──► df_clean
                    │                │
                    ▼                │
              Target Generator      │
                    │                │
                    ▼                ▼
              period_targets    Economics Engine ──► ROI curves
                    │                │
                    │                │    Hiring Plan
                    │                │        │
                    │                │        ▼
                    │                │   AE Capacity Model ──► capacity_by_month
                    │                │        │
                    └───────┬────────┘        │
                            ▼                 │
                      Optimizer ◄─────────────┘
                            │
                            ▼
                      allocation_results
                            │
                    ┌───────┼────────┐
                    ▼       ▼        ▼
               Recovery  Validation  Lever Analysis Engine
                    │       │             │
                    ▼       ▼             ▼
               recovery  pass/fail    lever analysis outputs
               _plan     report       (CSV, TXT, JSON)
                    │
                    ▼
              Version Store
                    │
                    ▼
                    v001/
                    │
                    ▼
              What-If Engine
                    │
                    ▼
              scenario_comparison
```

### 3.2 Gap Attribution & Lever Recommendations (`--mode recommend`)

```
config.yaml ──► Config Manager
                    │
raw_data.csv ──► Data Loader ──► baselines {seg: {asp, win_rate}}
                    │
              Target Generator ──► targets
                    │
              AE Capacity Model ──► capacity (monthly HC + SAOs)
                    │
              [Optional: load saved results from VersionStore
               OR run AllocationOptimizer for fresh base]
                    │
                    ▼
              Lever Analysis Engine
                    │
                    ├──► Gap decomposition waterfall
                    │     (capacity shortfall / ASP decay / win-rate decay / cash cycle)
                    │
                    └──► Analytical sensitivities per lever
                              │
                              ▼
                         Ranked recommendations + narrative
                              │
                              ▼
                         Version Store (lever_analysis.csv,
                                        lever_recommendations.txt,
                                        lever_analysis_report.json)
```

### 3.3 Mid-Quarter Re-Plan

```
actuals.csv ──► Ad-Hoc Adjustment
                    │
                    ├──► Lock completed periods
                    │
                    ├──► Recalculate remaining target
                    │
                    └──► Re-trigger: Target Gen → Optimizer → Recovery → Validation
                              │
                              ▼
                         Version Store (new version)
                              │
                              ▼
                         Version Comparator (original vs. replan)
```

---

## 4. Config Schema

See `config.yaml` for the full schema with defaults and comments.

The config is structured into these sections:

| Section | Controls |
|---------|----------|
| `dimensions` | Which data columns are active, valid values per dimension |
| `targets` | Annual target, growth rate, planning mode, seasonality |
| `allocation` | Objective function, constraints, floor/ceiling |
| `economics` | Decay functions, calibration toggles, fallback rules |
| `ae_model` | Hiring plan, ramp parameters, shrinkage, stretch threshold |
| `what_if_scenarios` | Up to 5 named perturbation profiles (disabled by default; activate with `--enable-scenarios`) |
| `business_recommendations` | Lever bounds for gap analysis — one entry per lever with `config_path`, `max_delta`/`min_value`, `step`, `direction`, `label`, `unit` |
| `system` | Optimizer mode, confidence thresholds, output settings |

**`business_recommendations.levers` structure** (used by LeverAnalysisEngine):

```yaml
business_recommendations:
  levers:
    <lever_name>:
      config_path: "ae_model.starting_hc"   # dot-path to the config value to perturb
      category: "ae_capacity"               # ae_capacity | economics_decay | cash_cycle
      label: "Add tenured AEs"              # human-readable name for reports
      unit: "AEs"                           # unit of the delta
      direction: "increase"                 # increase | decrease
      max_delta: 20                         # max change from current value (or min_value for decrease)
      step: 5                               # step size for sensitivity display
```

Each lever in this section is automatically picked up by `LeverAnalysisEngine` and evaluated analytically when running `--mode recommend`.

---

## 5. File Structure

```
GTM_Planning_Engine/
├── ARCHITECTURE.md          ← This file
├── config.yaml              ← Default configuration
├── requirements.txt         ← Pinned dependencies
├── data/
│   ├── raw/                 ← Input data files
│   │   ├── 2025_actuals.csv
│   │   ├── ae_roster.csv
│   │   └── deal_data.csv    ← (dummy for now)
│   └── dummy/               ← Generated dummy data for demo
│       ├── deal_level_data.csv
│       └── ae_roster.csv
├── gtm_engine/              ← Python package
│   ├── __init__.py
│   ├── config_manager.py    ← Module 1
│   ├── data_loader.py       ← Module 2
│   ├── target_generator.py  ← Module 3
│   ├── economics_engine.py  ← Module 4 (includes calibration.py)
│   ├── ae_capacity.py       ← Module 5
│   ├── optimizer.py         ← Module 6
│   ├── recovery.py          ← Module 7
│   ├── validation.py        ← Module 8
│   ├── adjustments.py       ← Module 9
│   ├── what_if.py           ← Module 10
│   ├── version_store.py     ← Module 11
│   ├── comparator.py        ← Module 12
│   └── lever_analysis.py    ← Module 13
├── versions/                ← Stored plan versions
│   └── (created at runtime)
├── notebooks/
│   └── gtm_planning.ipynb   ← Orchestration notebook
└── tests/                   ← (future) unit tests
    └── (one test file per module)
```

---

## 6. Build Phases

| Phase | Modules | Outcome |
|-------|---------|---------|
| **Phase 1: Foundation** | Config Manager, Data Loader, Version Store | Config-driven data pipeline. Can load and version data. |
| **Phase 2: Core Engine** | Target Generator, Optimizer (greedy first, then solver) | Feature parity with case study, but config-driven and repeatable. |
| **Phase 3: Depth** | Economics Engine, AE Capacity Model | Decay curves and workforce planning. System becomes materially better than case study. |
| **Phase 4: Operations** | Recovery, Validation, Ad-Hoc Adjustment | Continuous re-planning capability. Production-ready. |
| **Phase 5: Analysis** | What-If Engine, Version Comparator | Scenario analysis and decision support. The "wow factor." |

---

## 7. Technical Requirements

| Requirement | Specification |
|-------------|--------------|
| Python version | 3.10+ (stable on Apple Silicon / M3) |
| Key dependencies | pandas >= 2.0, numpy >= 1.24, scipy >= 1.11, pyyaml >= 6.0, openpyxl >= 3.1 |
| Optional (Phase 5+) | plotly >= 5.18 (interactive charts for future UI layer) |
| Platform | macOS (M3), local execution. Jupyter Notebook for orchestration. |
| Data scale | Well within local memory limits. Expect < 100K rows for foreseeable use. |

---

## 8. Adjacent Builds

The current architecture implements a **deterministic optimization engine** that allocates resources given fixed inputs (targets, seasonality, economics, capacity). While sufficient for baseline planning, this architecture can be extended with a **probabilistic forecasting layer** to generate better inputs by modeling market dynamics, strategic intent, and uncertainty.

### 8.1 Forecasting Engine Architecture

A forecasting engine sits upstream of the optimizer and produces three outputs: **demand forecast**, **economics forecast**, and **capacity forecast**. These become probabilistic inputs (P10/P50/P90 distributions) rather than point estimates, enabling scenario-based planning.

**Three core modules:**

| Module | Purpose | Key Features |
|---------|---------|---------------|
| **Demand Forecaster** | Forecast SAO demand by product × channel × month | Prophet-based time series, strategic bet overlays, macro indicator integration, Monte Carlo simulation |
| **Economics Forecaster** | Forecast ASP and win rate evolution | Mix-shift models, competitive dynamics, AE tenure effects, trend extrapolation |
| **Capacity Forecaster** | Forecast AE capacity under uncertainty | Stochastic hiring/attrition, empirical ramp distributions, scenario generation |

### 8.2 Strategic Bet Management

The forecasting layer introduces **exploration-exploitation trade-offs**: investing in new products/markets despite uncertain economics. This requires mechanisms for:

- **Strategic override flags** to mark high-priority segments (e.g., Payroll expansion)
- **Learning bonuses** in the objective function to value information from running deals through uncertain segments
- **Separate tracking** of exploration costs vs. exploitation revenue
- **Bayesian updating** to refine estimates as data accumulates

### 8.3 Implementation Path

The forecasting engine is comparable in complexity to the existing optimisation engine. Key differences:

| Dimension | Current System | Forecasting Layer |
|-----------|---------------|-------------------|
| **Uncertainty** | Handled via what-if scenarios (manual) | Built into all forecasts (probabilistic) |
| **Parameters** | Fixed values in config | Distributions updated from data |
| **Optimization** | Deterministic allocation | Scenario-based planning with confidence intervals |
| **New dependencies** | None | Prophet, PyMC (optional for Bayesian models) |
| **New data requirements** | Historical actuals only | Deal-level timestamps, HR data, marketing calendar |

See [Open Questions & Forecasting Engine](file:///Users/shourjosmac/Documents/Claude/Projects/Interview%20prep/GTM_Planning_Engine/WARP-GTM%20Planning%20Engine_%20Answering%20Open%20Questions%20&%20Building%20a%20Forecasting%20Engine%20for%20Remote.md) for complete architecture, resolution strategies for all hardcoded parameters, and a 10-week implementation roadmap. |
