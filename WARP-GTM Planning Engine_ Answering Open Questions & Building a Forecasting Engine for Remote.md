# GTM Planning Engine: Open Questions & Forecasting Engine

---

## Part 1: The Open Questions — Catalogue & Resolution Strategy

Every hardcoded config value in the current engine is either (a) a best-guess estimate, (b) derived from qualitative feedback, or (c) a structural assumption with no empirical basis. Below is a systematic inventory of each, the methodological choices for resolving it, and the trade-offs of each choice.

---

### 1.1 Seasonality Weights (`targets.seasonality_weights`)

**Current state:** 12 manually set weights (month_1=0.055 … month_12=0.095) described as reflecting "observed peaks in months 4, 7, 10, 11." No derivation method documented.

**Scientific resolution options:**

| Approach | How it works | Pros | Cons |
|---|---|---|---|
| A. Cohort-decomposition of historical bookings | Decompose 2-3 years of monthly bookings using STL or X-13-ARIMA-SEATS. Extract the seasonal component. Normalise to sum=1. | Gold standard for seasonality. Separates trend from cycle from noise. | Requires ≥24 months of clean bookings history at monthly grain. Remote may not have this by product×channel. |
| B. Win-date histogram | Bucket all closed-won deals by close month. Compute the share of annual deals per month. Smooth via kernel density estimation. | Simple, intuitive, directly uses deal data. | Conflates seasonality with sales capacity fluctuations (e.g., if you hired more reps in Q3, Q3 looks "seasonal"). |
| C. Pipeline-stage timing | Use opportunity creation→close timestamps to infer natural sales-cycle seasonality independent of capacity. Separate demand seasonality from supply. | Disentangles demand from supply. | Requires CRM stage-level data (not just closed deals). |
| D. External proxy | Use macro proxies (e.g., global hiring activity indices, LinkedIn job-posting volume, budget-cycle timing) as external regressors. | Captures market-driven seasonality that may not yet appear in Remote's own data, especially for new products/markets. | Requires finding and validating the right external series. Risk of spurious correlation. |

**Recommendation for real-world Remote context:** Combine A + D. Use STL decomposition on historical bookings as the base, then overlay external regressors (e.g., global hiring volume from LinkedIn Economic Graph data, which tracks international job postings) to capture market-level seasonality. For new products/markets with no history, use D alone with a Bayesian prior from the nearest analogue product.

---

### 1.2 Decay Functions & Parameters (`economics.default_decay`)

**Current state:** ASP decay = exponential, rate=0.001, threshold=340, floor=0.75. Win rate decay = linear, rate=0.005, threshold=260, floor=0.80. All best-guess. The config even includes a "rate magnitude guide" acknowledging the guesswork.

**Scientific resolution options:**

| Approach | How it works | Pros | Cons |
|---|---|---|---|
| A. Empirical curve fitting (CalibrationEngine already scaffolded) | Bin historical deals by volume quintile per segment. Fit decay curves via scipy curve_fit. | Directly data-driven. The code already exists. | Needs min_deals_for_fit (currently 5, should be ≥30 for statistical significance). Sensitive to binning choices. May overfit if few segments have high volume. |
| B. Natural experiment / regression discontinuity | Identify months where SAO volume jumped due to hiring or marketing campaigns. Use the before/after contrast to estimate marginal decay. | Identifies causal decay rather than just correlation. | Requires clear volume shocks and enough of them. Hard to find clean natural experiments. |
| C. Bayesian hierarchical model | Pool information across segments. Model decay parameters as draws from a shared prior. Segments with sparse data borrow strength from rich segments. | Handles sparsity elegantly. Produces uncertainty intervals. Naturally implements the fallback hierarchy already in config. | More complex to implement. Requires probabilistic programming (PyMC, Stan). |
| D. A/B testing of SAO allocation | Deliberately over-allocate SAOs to one segment for one quarter, measure ASP/win-rate response. | The only truly causal approach. | Expensive: you're deliberately allocating sub-optimally to learn. Requires executive buy-in to run a controlled experiment on revenue. |

**Recommendation:** Start with A (already scaffolded), then migrate to C as data volume grows. D is the gold standard but only viable once the business is large enough that the learning cost is immaterial relative to total revenue.

**Crucially:** ASP and win-rate decay should also be decomposed by *reason*. ASP decay could be driven by (i) moving downmarket to smaller customers, (ii) competitive price pressure at high volume, or (iii) discounting to hit volume targets. Each has different implications for whether the decay is "real" or self-inflicted.

---

### 1.3 AE Capacity Parameters

**Current state:** productivity_per_ae=45 SAOs/month, ramp_duration=45 days, mentoring_overhead=5%, PTO=8%, admin=5%, enablement=3%, attrition=10%.

**Key open questions:**
- **45 SAOs/month per AE** — Is this observed? What's the distribution? Is this the mean or median? Is there a top-decile vs. bottom-decile spread that matters for planning?
- **45-day ramp** — Extremely fast for a complex product like EOR. Industry benchmarks suggest 3-6 months for enterprise SaaS reps. Is this aspirational or measured?
- **Linear ramp** — Real ramp curves are typically S-shaped (slow start, rapid middle, plateau). Linear is a simplification.
- **5% mentoring overhead** — Source?
- **10% attrition** — Is this involuntary + voluntary? Regrettable vs. non-regrettable?

**Resolution approaches:**

| Parameter | Best method | Fallback method |
|---|---|---|
| Productivity per AE | Compute from CRM: closed deals per AE per month, segmented by tenure cohort. Use median, not mean (skewed by top performers). | Survey sales leadership for best guess + range. |
| Ramp duration & curve shape | Fit an empirical ramp curve: for each AE, plot monthly productivity as % of their eventual steady-state, indexed from hire date. Fit logistic (S-curve). | Use industry benchmarks (Bridge Group, SaaStr surveys: median B2B SaaS ramp = 4.5 months). |
| Mentoring overhead | Time-study: have managers log mentoring hours for 2 months. Or proxy from CRM activity — do tenured AEs' own metrics dip during new-hire periods? | Use published benchmarks (typically 10-15% for first 90 days). |
| Attrition | HR data: split into voluntary/involuntary, regrettable/non-regrettable. Compute TTM rolling rate. | Industry benchmark for tech sales: 15-20% voluntary. |

---

### 1.4 Share Floor/Ceiling (0.03 / 0.40)

**Current state:** 3% floor, 40% ceiling. These are pure judgment calls.

**Resolution options:**
- **Data-driven floor:** Set floor = max(minimum_viable_volume / total_annual_SAOs, some_small_constant). Where minimum_viable_volume = the SAO count below which you can't sustain a single dedicated AE (say 20 SAOs/month = ~240/year). This makes the floor a function of org size, not a constant.
- **Data-driven ceiling:** Concentration risk analysis. Set ceiling such that HHI (Herfindahl-Hirschman Index) doesn't exceed a threshold. Or: ceiling = share at which marginal ROI drops below the average ROI of the next-best segment (the indifference point).
- **Practical override:** Some ceilings are strategic, not economic. E.g., "we don't want >30% of revenue from Partner because partner relationships are fragile." These should be explicitly labelled as strategic constraints vs. economic constraints.

---

### 1.5 Cash Cycle Distributions

**Current state:** EOR: {0: 0.10, 1: 0.30, 2: 0.40, 3: 0.20}, CM: {0: 0.40, 1: 0.35, 2: 0.15, 3: 0.10}. All hardcoded.

**Resolution:** This is one of the easiest to derive empirically. For every closed-won deal, compute (close_date - SAO_accepted_date) in months. Group by product. Fit an empirical distribution (histogram → normalised probabilities by month bucket). Update quarterly.

---

### 1.6 Confidence Thresholds (high=6, medium=3)

**Current state:** 6 deals = high confidence, 3 = medium. These are extremely low for statistical confidence.

**Resolution:** Use the concept of the margin of error. For a metric like ASP with coefficient of variation CV, you need n ≥ (z × CV / E)² deals for a margin of error E at confidence level z. For example, if ASP has CV=0.5 and you want ±20% precision at 90% confidence: n ≥ (1.645 × 0.5 / 0.2)² ≈ 17 deals. The current threshold of 6 gives very wide confidence intervals.

---

### 1.7 Growth Rate (50%) and Annual Target ($188M)

**Current state:** 50% YoY growth from $125M. These are presumably given by leadership, not estimated.

**Key question:** Is 50% growth a *target* (aspiration) or a *forecast* (expectation)? This distinction is critical. If it's a target, the optimisation engine should work backward from it. If it's a forecast, there should be a probability attached (e.g., "50% growth has a 30% probability; base case is 35% growth").

---

## Part 2: How Choices Change When Taken Together

---

### 2.1 Isolated (Scientific Best) vs. Bundled (Real-World)

**In isolation**, the scientifically cleanest answer for each open question is:

| Open Question | Scientific Best |
|---|---|
| Seasonality | STL decomposition + external regressors |
| Decay | Bayesian hierarchical models |
| AE capacity | CRM-derived empirical curves |
| Cash cycle | Empirical distributions from CRM timestamps |
| Confidence | Statistically-grounded thresholds (~20-30 deals) |
| Growth target | Probabilistic scenario tree |

**Taken together in the real world**, these choices interact:

1. **Data availability constrains everything.** If Remote has <2 years of clean CRM data by product×channel×month, STL decomposition won't work, Bayesian hierarchical models won't converge, and empirical ramp curves will be noisy. The practical answer may be: start with informed priors from industry benchmarks, update as data accumulates.
2. **Organisational buy-in matters.** A Bayesian hierarchical model for decay curves is correct but opaque. Sales leaders need to understand *why* the model says to allocate 37% to EOR.Marketing. Greedy mode with simple decay is less optimal but more explainable.
3. **Speed of iteration matters.** Remote is a high-growth startup (50% YoY). The market is shifting fast (Atlas acquisition, Deel competition). A lightweight model that updates quarterly is more valuable than a perfect model that takes 6 months to build.
4. **Strategic bets break historical patterns.** If Remote decides to push Payroll aggressively in 2026, historical data for Payroll will be sparse and the decay curves will be uninformative. The forecasting engine must accommodate expert overrides for strategic bets.

---

### 2.2 Real-World Scenario Bundles

---

#### Scenario A: "Data-Rich Operator" (Remote has 3+ years of clean CRM data, strong RevOps team)

| Parameter | Approach |
|---|---|
| Seasonality | STL + external regressors |
| Decay | Calibrated curves via CalibrationEngine → Bayesian hierarchical as data grows |
| AE capacity | Empirical cohort analysis from CRM |
| Cash cycle | Empirical from CRM timestamps |
| Confidence | n=20 for high, n=10 for medium |
| Growth | Probabilistic scenarios with Monte Carlo simulation |

---

#### Scenario B: "Fast-Moving Scaler" (Remote has ~18 months of data, small RevOps, decisions needed now)

| Parameter | Approach |
|---|---|
| Seasonality | Win-date histogram from available data + executive judgment for new products |
| Decay | CalibrationEngine where data exists (EOR.Marketing, EOR.Partner), defaults + expert judgment elsewhere |
| AE capacity | Sales leadership estimates validated against CRM spot-checks |
| Cash cycle | CRM-derived where possible, exec estimates for new products |
| Confidence | Lower bar (n=10 high, n=5 medium) with explicit "low confidence" tagging |
| Growth | Two scenarios (base + stretch) without full Monte Carlo |

---

#### Scenario C: "Strategic Pivot" (Remote launches new product line, enters new region — no historical data)

| Parameter | Approach |
|---|---|
| Seasonality | External proxy (market hiring indices) + analogy from nearest existing product |
| Decay | Pure expert judgment with wide floor_multipliers and conservative ceilings |
| AE capacity | Industry benchmarks + 20% haircut for new-market unfamiliarity |
| Cash cycle | Analogy from nearest product + longer tail assumption |
| Confidence | Everything is low-confidence by definition; the engine should run in "exploration mode" with wide guardrails |
| Growth | Top-down TAM-based estimate, not bottom-up |

---

## Part 3: The Forecasting Engine

---

### 3.1 Why It's Needed

The current engine is a **pure optimiser**: given a fixed target ($188M), fixed seasonality, fixed economics, and fixed capacity, it finds the best allocation. But it answers "how" — not "what" or "why."

A forecasting engine answers:

| Question | What it forecasts |
|---|---|
| **What** will demand look like? | SAO volume forecast by segment |
| **What** will economics look like? | ASP, win rate evolution |
| **What** will capacity look like? | Attrition, hiring success, ramp reality |
| **What** should the target be? | Given market conditions, competitive dynamics, strategic bets |

The forecasting engine produces the *inputs* that the optimisation engine consumes.

---

### 3.2 Remote's Strategic Context (from research)

**Company profile:**

| Attribute | Detail |
|---|---|
| Revenue | ~$131M (2025) |
| Valuation | $3B (2022) |
| Funding | $506M raised (Series C) |
| Employees | 14,000+ |
| Countries | 85+ (owned entities only — a key differentiator vs. Deel's 160+ partner-model countries) |
| Products | EOR (core, highest ASP), Contractor Management (lower ASP, faster cycle), Payroll (newest, highest ASP potential, lowest volume) |
| Recent acquisition | Atlas (Jan 2026) — expands coverage |
| CEO | Job van der Voort |
| CRO | John Kelly |
| Key competitor | Deel (~$1B ARR, 22.5% market share vs. Remote's ~18.3%) |

**Market context:**

| Metric | Detail |
|---|---|
| Global EOR market | ~$5-7B in 2025, growing at 7-15% CAGR depending on definition |
| EOR adoption | 55% of internationally-hiring companies already use an EOR |
| International hiring trend | 73% of companies expect >50% of new hires to be international by 2026 |
| Remote's model | Owned-entity model is a compliance advantage but a coverage disadvantage (85 vs. 160+ countries) |
| Regional growth | APAC is fastest-growing region — where Remote has limited coverage |
| New entrants | Fintech players (Revolut GlobalHire) entering the market in 2026 |

**Strategic implications for the forecasting engine:**
- 50% growth ($125M → $188M) is ambitious in a market growing at 7-15% — implies significant share gain or product expansion
- Payroll is the strategic bet product: highest ASP, no historical data, longest sales cycle
- APAC expansion (post-Atlas acquisition) = new market with no history
- Competitive pressure from Deel and incoming fintech players may compress ASP, especially for CM

---

### 3.3 Architecture of the Forecasting Engine

The forecasting engine sits *upstream* of the current optimisation engine and produces three outputs: **demand forecast**, **economics forecast**, and **capacity forecast**. These become the inputs to the optimiser.

```
┌────────────────────────────────────────────────────────────────┐
│                    FORECASTING ENGINE                          │
│                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ Demand        │  │ Economics    │  │ Capacity             │ │
│  │ Forecaster    │  │ Forecaster   │  │ Forecaster           │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘ │
│         │                 │                      │             │
│         ▼                 ▼                      ▼             │
│  SAO demand by       ASP & win rate          AE supply by     │
│  segment × month     by segment × month      month            │
│         │                 │                      │             │
│         ├─── Seasonality weights (derived) ──────┤             │
│         ├─── Growth target (probabilistic) ──────┤             │
│         ├─── Strategic overrides ────────────────┤             │
│         │                                        │             │
├─────────┼────────────────────────────────────────┼─────────────┤
│         │     INTERFACE TO OPTIMISER              │             │
│         ▼                                        ▼             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │             Current Optimisation Engine                   │  │
│  │  (Target Generator → Economics → AE Capacity → Optimizer) │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

---

### 3.4 Module Design

---

#### Module F1: Demand Forecaster

**Purpose**: Forecast SAO demand by product × channel × month, incorporating both historical patterns and strategic bets.

**Key insight**: Seasonality weights in the current system are static. In reality, they must account for:
- Historical seasonal patterns (budget cycles, end-of-quarter rushes)
- Strategic bets ("push Payroll in Q3 2026" — has no history)
- Market dynamics (APAC launch, competitive response)
- Marketing spend timing (campaigns drive SAO spikes)
- Macro environment (economic slowdown reduces hiring → reduces EOR demand)

**Inputs**:
- Historical monthly SAOs by segment (from CRM)
- Strategic bet definitions: {product, target_share_of_pipe, start_month, confidence_level}
- Marketing calendar: {campaign, expected_SAO_impact, channel, months}
- Macro indicators: global hiring index, tech layoff tracker, etc.
- Executive overrides: "I believe Payroll will be 15% of pipe by Q4"

**Method**:
1. Base forecast: Time series model (Prophet or ETS) on historical SAOs per segment
2. Adjustment layer: Additive/multiplicative adjustments for strategic bets and marketing campaigns
3. Macro overlay: Regression of historical SAOs on macro indicators to estimate macro sensitivity
4. Scenario generation: Monte Carlo simulation producing P10/P50/P90 demand curves

**Output**: Probabilistic SAO forecast by segment × month (replaces the fixed `seasonality_weights` + `annual_target` in config)

---

#### Module F2: Economics Forecaster

**Purpose**: Forecast how ASP and win rates will evolve, rather than assuming static baselines with mechanical decay.

**Key insight**: The current engine applies decay as a mathematical function of volume. In reality, ASP and win rate are driven by:
- **Mix shift:** As you move into new segments (e.g., SMB), average ASP drops even if per-segment ASP is stable
- **Competitive dynamics:** Deel's pricing pressure may compress EOR ASP over time regardless of volume
- **Product maturity:** Payroll ASP may *increase* as Remote moves upmarket (inverse of typical decay)
- **Sales team composition:** Junior reps have lower win rates regardless of volume

**Inputs**:
- Historical ASP and win rate by segment × month
- Competitive intelligence (pricing changes, feature launches)
- Product roadmap (new tiers, pricing changes)
- AE tenure distribution (from HR data)

**Method**:
1. Base trend: Exponential smoothing of ASP and win rate per segment
2. Mix-shift model: Forecast the segment mix separately, then compute weighted-average economics
3. Competitive adjustment: Expert-input multipliers for competitive pressure scenarios
4. AE-tenure adjustment: Model win rate as a function of AE tenure, then apply to the forecasted tenure distribution

**Output**: ASP and win rate forecast by segment × month (replaces static `baselines` from data_loader)

---

#### Module F3: Capacity Forecaster

**Purpose**: Forecast AE capacity under uncertainty, rather than assuming a deterministic hiring plan.

**Key insight**: The current AE capacity model is deterministic: you input a hiring plan and it outputs capacity. But hiring plans are uncertain:
- Recruiter capacity constrains hiring velocity
- Offer acceptance rates vary
- Actual attrition differs from planned
- Ramp times vary by individual

**Inputs**:
- Planned hiring tranches (from current config)
- Historical hiring velocity (offers made → accepted → started)
- Historical attrition by tenure cohort
- Historical ramp curves by AE cohort

**Method**:
1. Stochastic hiring model: Each tranche has a probability distribution of actual start dates and sizes
2. Stochastic attrition: Model monthly attrition as a Poisson process calibrated to historical rate
3. Empirical ramp distribution: Instead of a single linear curve, use the actual distribution of ramp trajectories
4. Scenario generation: Monte Carlo producing P10/P50/P90 capacity curves

**Output**: Probabilistic capacity forecast by month (replaces the deterministic `ae_capacity.calculate()`)

---

### 3.5 Strategic Bets & The Exploration-Exploitation Trade-off

The most important conceptual addition the forecasting engine brings is the handling of **strategic bets** — investments in products/markets that may cannibalise proven revenue sources.

**Example:** Remote wants to grow Payroll from ~7% of bookings to 20% by FY27. Payroll has:
- Highest ASP ($12K-$20K) but longest sales cycle
- Fewest historical deals → low confidence in all parameters
- Requires specialised AEs (can't just reassign EOR reps)
- May cannibalise some EOR deals (customers who wanted Payroll may settle for EOR)

The current optimiser, given low confidence and low historical volume, will *under-allocate* to Payroll because its decay parameters are uncertain and its ROI is conservatively estimated. This is the **exploitation** bias: the engine favours what it knows.

The forecasting engine must support **exploration**: deliberately over-allocating to strategic bets despite uncertain economics, tracking the results, and updating estimates. This requires:

| # | Mechanism | Description |
|---|-----------|-------------|
| 1 | **Strategic override flag** | `is_strategic_bet: true` for Payroll segments in config |
| 2 | **Modified objective function** | Strategic bet segments get a "learning bonus" in the objective — the value of information from running more deals through the segment |
| 3 | **Separate tracking** | Strategic bet allocations are tracked separately so their "cost" (revenue foregone vs. proven segments) is visible |
| 4 | **Bayesian updating** | After each quarter, the forecasting engine updates its priors for strategic bet segments using the new data, and the allocation gradually shifts from exploration to exploitation |

---

### 3.6 Implementation Roadmap

| Phase | Timeline | Activities | Result |
|-------|----------|------------|--------|
| **Phase 1: Empirical calibration** | Week 1-2 | Derive seasonality weights from 2025 actuals using win-date histogram. Fit decay curves using CalibrationEngine on available data. Derive cash cycle distributions from deal timestamps. Compute empirical AE productivity and ramp curves from HR/CRM data. Raise confidence thresholds to statistically meaningful levels. | Same engine architecture, better parameters |
| **Phase 2: Demand Forecaster (F1)** | Week 3-5 | Implement Prophet-based time series model for SAO forecasting. Add strategic bet override mechanism. Build scenario generator (Monte Carlo on demand). Wire output into TargetGenerator as a replacement for static seasonality weights. | Probabilistic demand forecasting |
| **Phase 3: Economics & Capacity Forecasters (F2, F3)** | Week 6-8 | Implement economics trend model with mix-shift and competitive adjustments. Implement stochastic capacity model. Wire both into the optimiser pipeline. | Full probabilistic input layer |
| **Phase 4: Integration & Scenario Planning** | Week 9-10 | Build end-to-end pipeline: Forecast → Optimise → Validate → Compare. Implement the exploration-exploitation framework for strategic bets. Build dashboard showing P10/P50/P90 outcomes for key metrics. Scenario comparison: "What if Payroll takes off?" vs. "What if Deel cuts pricing 20%?" | Complete forecasting + optimisation system |

---

### 3.7 Complexity Assessment

The forecasting engine is comparable in complexity to the existing optimisation engine:

| Dimension | Detail |
|-----------|--------|
| New modules | ~5-6 (3 forecasters + scenario generator + strategic bet manager + integration layer) |
| New dependencies | Prophet (or statsmodels), PyMC (optional, for Bayesian models) |
| New data requirements | CRM deal-level timestamps, HR hire/departure dates, marketing calendar |
| Key difference | The forecasting engine is *probabilistic* where the optimisation engine is *deterministic*. Outputs are distributions, not point estimates, and the reporting layer must handle uncertainty ranges. |

---

## Summary

**Open questions** are best resolved through a phased approach: start with empirical calibration of existing parameters using available data (cheap, fast), then progressively add statistical sophistication as data accumulates (Bayesian hierarchical models, stochastic simulation).

**The forecasting engine** is the missing upstream layer that converts strategic intent and market reality into the structured inputs the optimiser needs. Without it, the optimiser is optimising against guesses. With it, the optimiser is optimising against probabilistic forecasts that incorporate historical patterns, strategic bets, competitive dynamics, and macro conditions.

The two tasks are deeply intertwined: answering the open questions *is* building the calibration layer of the forecasting engine. The forecasting engine *is* the systematic way to keep those answers updated as reality changes.
