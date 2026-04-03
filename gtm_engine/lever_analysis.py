"""
Lever Analysis Engine — Analytical Sensitivity & Gap Attribution Module

Purpose:
    When the plan misses its bookings target, this module:
      1. Decomposes the gap into its root causes (capacity constraint, ASP
         decay, win-rate decay, cash cycle deferral) using a waterfall model.
      2. Computes the sensitivity of bookings to each operational lever
         analytically — no pipeline re-runs required.
      3. Ranks levers by their estimated impact on closing the gap.
      4. Produces plain-language recommendations for leadership.

Mathematical approach:
    The bookings identity is:
        bookings_m = Σ_s SAOs_s × ASP_s(vol) × CW_s(vol) × IWF_s

    Each factor maps to a lever category:
        SAOs_s        ← AE capacity levers  (HC, ramp, mentoring, shrinkage, backfill)
        ASP_s(vol)    ← Economics decay levers  (asp decay rate / floor)
        CW_s(vol)     ← Economics decay levers  (win-rate decay rate / floor)
        IWF_s         ← Cash cycle levers  (close acceleration)

    Sensitivity = partial derivative of total bookings with respect to each
    lever, computed from closed-form expressions — not from finite differences
    that require re-running the optimizer.

    The SAO shadow price π (bookings per incremental SAO delivered in
    constrained months) is the bridge between capacity levers and bookings:
        π_m = total_bookings_m / delivered_saos_m   (constrained months only)

    For unconstrained months, additional capacity has zero marginal value.

Gap decomposition waterfall:
    Baseline (no decay, full capacity)
    − Capacity shortfall loss       [capacity constraint]
    − ASP decay loss                [volume-driven ASP compression]
    − Win-rate decay loss           [volume-driven CW compression]
    − Cash cycle deferral           [deals closing outside horizon]
    = Actual projected bookings
    − Annual target
    = Gap
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# ── Data structures ────────────────────────────────────────────────────


@dataclass
class GapDecomposition:
    """Waterfall attribution of the bookings gap."""
    annual_target: float
    baseline_bookings: float          # bookings if no decay and no capacity constraint
    capacity_shortfall_loss: float    # lost because capacity < demand
    asp_decay_loss: float             # lost because ASP decayed at volume
    win_rate_decay_loss: float        # lost because win rate decayed at volume
    cash_cycle_deferral: float        # deferred outside planning horizon
    actual_bookings: float
    gap: float                        # target - actual


@dataclass
class LeverSensitivity:
    """Analytical sensitivity result for one lever."""
    lever_name: str
    label: str
    category: str
    unit: str
    current_value: float
    bound_value: float
    direction: str
    estimated_gain: float             # total $ bookings gain at bound
    gain_pct_of_gap: float            # % of gap this lever closes
    gain_pct_of_base: float           # % lift on base bookings
    business_context: str             # plain-English: what this variable means & why it matters
    mechanism: str                    # calculation trace for analysts
    recommendation: str               # single-line action statement (x → y)


# ── Main engine ────────────────────────────────────────────────────────


class LeverAnalysisEngine:
    """
    Analytical sensitivity engine for GTM planning lever analysis.

    Attributes:
        config:    Full config dict (plain dict, not ConfigManager).
        levers:    Lever definitions from config['business_recommendations']['levers'].
    """

    def __init__(self, config: dict) -> None:
        self.config = config
        br = config.get("business_recommendations", {})
        self.levers = br.get("levers", {})
        if not self.levers:
            raise ValueError(
                "No levers defined in config['business_recommendations']['levers']"
            )

    # ── Public API ─────────────────────────────────────────────────

    def analyze(
        self,
        base_results: pd.DataFrame,
        capacity: pd.DataFrame,
        targets: pd.DataFrame,
        baselines: Dict[str, Dict[str, float]],
    ) -> Dict[str, Any]:
        """
        Run analytical sensitivity analysis and produce recommendations.

        No pipeline re-runs required. All sensitivities are computed from
        closed-form expressions derived from the planning model's math.

        Args:
            base_results: Allocation results from run_plan (segment × month).
                          Must include: required_saos, effective_asp,
                          effective_cw_rate, projected_bookings, capacity_flag,
                          and optionally in_window_factor / in_window_bookings.
            capacity:     Monthly capacity DataFrame from AECapacityModel.
                          Must include: month, effective_capacity_saos,
                          hc_tenured, hc_ramping, hc_total,
                          mentoring_tax, shrinkage_rate.
            targets:      Monthly targets DataFrame with target_revenue column.
            baselines:    Segment baselines dict {seg: {asp, win_rate}}.

        Returns:
            Dict with keys:
                decomposition       GapDecomposition waterfall
                lever_results       List[LeverSensitivity] sorted by estimated_gain
                recommendations_text Plain-language narrative
                summary_df          Pandas DataFrame of lever results
        """
        annual_target = self.config.get("targets", {}).get("annual_target", 0)
        actual_bookings = base_results["projected_bookings"].sum()
        gap = annual_target - actual_bookings

        # ── Step 1: Precompute shared quantities ───────────────────
        sao_shadow_price = self._compute_sao_shadow_price(base_results, capacity)
        total_missed_saos = self._total_missed_saos(base_results, capacity)

        # ── Step 2: Gap decomposition waterfall ───────────────────
        decomp = self._decompose_gap(
            base_results, capacity, targets, baselines, annual_target, actual_bookings
        )

        # ── Step 3: Analytical sensitivities for each lever ────────
        lever_results: List[LeverSensitivity] = []
        for lever_name, lever_cfg in self.levers.items():
            result = self._compute_lever_sensitivity(
                lever_name, lever_cfg,
                base_results, capacity, actual_bookings,
                sao_shadow_price, total_missed_saos,
            )
            if result is not None:
                lever_results.append(result)

        lever_results.sort(key=lambda r: r.estimated_gain, reverse=True)

        text = self._build_narrative(gap, annual_target, actual_bookings, decomp, lever_results)
        summary_df = self._to_dataframe(lever_results, gap)

        return {
            "decomposition": decomp,
            "lever_results": lever_results,
            "recommendations_text": text,
            "summary_df": summary_df,
            "gap": gap,
            "annual_target": annual_target,
            "actual_bookings": actual_bookings,
            "sao_shadow_price": sao_shadow_price,
        }

    def print_recommendations(self, report: Dict[str, Any]) -> None:
        print(report["recommendations_text"])

    def to_dataframe(self, report: Dict[str, Any]) -> pd.DataFrame:
        return report.get("summary_df", pd.DataFrame())

    # ── Gap decomposition ──────────────────────────────────────────

    def _decompose_gap(
        self,
        results: pd.DataFrame,
        capacity: pd.DataFrame,
        targets: pd.DataFrame,
        baselines: Dict[str, Dict[str, float]],
        annual_target: float,
        actual_bookings: float,
    ) -> GapDecomposition:
        """
        Decompose gap into capacity / ASP decay / win-rate decay / cash cycle.

        Waterfall logic:
          1. Baseline = what bookings would be with zero decay + full capacity
             = Σ_s required_saos_s × base_ASP_s × base_CW_s
          2. Capacity shortfall = lost bookings because effective_capacity < required_saos
          3. ASP decay loss = bookings lost because ASP < base_ASP at volume
          4. Win-rate decay loss = bookings lost because CW < base_CW at volume
          5. Cash cycle deferral = projected_bookings - in_window_bookings
        """
        # Required SAOs per month (what the optimizer demanded)
        if "month" in results.columns and "required_saos" in results.columns:
            monthly_demand = results.groupby("month")["required_saos"].sum()
        else:
            monthly_demand = pd.Series(dtype=float)

        cap_indexed = capacity.set_index("month")["effective_capacity_saos"] \
            if "month" in capacity.columns else pd.Series(dtype=float)

        # Capacity shortfall loss
        cap_shortfall_loss = 0.0
        if not monthly_demand.empty and not cap_indexed.empty:
            sao_shadow = actual_bookings / results["required_saos"].sum() \
                if results["required_saos"].sum() > 0 else 0
            for month in monthly_demand.index:
                if month in cap_indexed.index:
                    demanded = monthly_demand[month]
                    available = cap_indexed[month]
                    if demanded > available:
                        cap_shortfall_loss += (demanded - available) * sao_shadow

        # ASP decay loss: baseline_asp × saos × cw vs actual_bookings
        asp_decay_loss = 0.0
        win_rate_decay_loss = 0.0
        baseline_bookings = 0.0

        for seg, base in baselines.items():
            seg_rows = results[results["segment_key"] == seg] \
                if "segment_key" in results.columns else pd.DataFrame()
            if seg_rows.empty and "segment" in results.columns:
                seg_rows = results[results["segment"] == seg]
            if seg_rows.empty:
                continue

            base_asp = base.get("asp", 0)
            base_cw = base.get("win_rate", 0)
            total_saos = seg_rows["required_saos"].sum()
            actual_asp = (seg_rows["effective_asp"] * seg_rows["required_saos"]).sum() / total_saos \
                if total_saos > 0 else 0
            actual_cw = (seg_rows["effective_cw_rate"] * seg_rows["required_saos"]).sum() / total_saos \
                if total_saos > 0 else 0

            in_window_factor = 1.0
            if "in_window_factor" in seg_rows.columns and total_saos > 0:
                in_window_factor = (seg_rows["in_window_factor"] * seg_rows["required_saos"]).sum() / total_saos

            baseline_bookings += total_saos * base_asp * base_cw
            asp_decay_loss += total_saos * (base_asp - actual_asp) * actual_cw * in_window_factor
            win_rate_decay_loss += total_saos * actual_asp * (base_cw - actual_cw) * in_window_factor

        # Cash cycle deferral
        if "in_window_bookings" in results.columns and "projected_bookings" in results.columns:
            cash_cycle_deferral = (
                results["projected_bookings"].sum() - results["in_window_bookings"].sum()
            )
        else:
            cash_cycle_deferral = 0.0

        return GapDecomposition(
            annual_target=annual_target,
            baseline_bookings=max(baseline_bookings, actual_bookings),
            capacity_shortfall_loss=max(0, cap_shortfall_loss),
            asp_decay_loss=max(0, asp_decay_loss),
            win_rate_decay_loss=max(0, win_rate_decay_loss),
            cash_cycle_deferral=max(0, cash_cycle_deferral),
            actual_bookings=actual_bookings,
            gap=annual_target - actual_bookings,
        )

    # ── SAO shadow price ───────────────────────────────────────────

    def _compute_sao_shadow_price(
        self,
        results: pd.DataFrame,
        capacity: pd.DataFrame,
    ) -> float:
        """
        Compute the bookings value of one additional deliverable SAO.

        In capacity-constrained months (demand > supply), each extra SAO
        unlocks π = bookings_m / delivered_saos_m in bookings.

        For unconstrained months, additional SAO capacity has zero marginal
        value (the optimizer is already allocating fewer than it could).
        """
        if results.empty or "month" not in results.columns:
            total_saos = results.get("required_saos", pd.Series([0])).sum()
            total_bookings = results.get("projected_bookings", pd.Series([0])).sum()
            return total_bookings / total_saos if total_saos > 0 else 0

        monthly_bookings = results.groupby("month")["projected_bookings"].sum()
        monthly_saos = results.groupby("month")["required_saos"].sum()

        # Identify constrained months
        cap_map = {}
        if "month" in capacity.columns and "effective_capacity_saos" in capacity.columns:
            cap_map = capacity.set_index("month")["effective_capacity_saos"].to_dict()

        constrained_bookings = 0.0
        constrained_saos = 0.0
        for month in monthly_bookings.index:
            demanded = monthly_saos.get(month, 0)
            available = cap_map.get(month, float("inf"))
            if demanded > available:
                constrained_bookings += monthly_bookings[month]
                constrained_saos += available

        if constrained_saos > 0:
            return constrained_bookings / constrained_saos

        # If no constrained months, use global average ROI
        total_saos = monthly_saos.sum()
        total_bookings = monthly_bookings.sum()
        return total_bookings / total_saos if total_saos > 0 else 0

    def _total_missed_saos(
        self,
        results: pd.DataFrame,
        capacity: pd.DataFrame,
    ) -> float:
        """Total SAOs the optimizer demanded but couldn't deliver due to capacity."""
        if "month" not in results.columns or capacity.empty:
            return 0.0

        monthly_demand = results.groupby("month")["required_saos"].sum()
        cap_map = {}
        if "month" in capacity.columns and "effective_capacity_saos" in capacity.columns:
            cap_map = capacity.set_index("month")["effective_capacity_saos"].to_dict()

        missed = 0.0
        for month in monthly_demand.index:
            demanded = monthly_demand[month]
            available = cap_map.get(month, float("inf"))
            if demanded > available:
                missed += demanded - available
        return missed

    # ── Lever sensitivities ────────────────────────────────────────

    def _compute_lever_sensitivity(
        self,
        lever_name: str,
        lever_cfg: dict,
        results: pd.DataFrame,
        capacity: pd.DataFrame,
        actual_bookings: float,
        sao_shadow_price: float,
        total_missed_saos: float,
    ) -> Optional[LeverSensitivity]:
        """Route to the appropriate analytical estimator for this lever."""
        category = lever_cfg.get("category", "")
        handlers = {
            "additional_hc":         self._sens_additional_hc,
            "ramp_duration":         self._sens_ramp_duration,
            "backfill_delay":        self._sens_backfill_delay,
            "mentoring_overhead":    self._sens_mentoring_overhead,
            "shrinkage_pto":         self._sens_shrinkage,
            "shrinkage_admin":       self._sens_shrinkage,
            "cash_cycle_acceleration": self._sens_cash_cycle,
            "asp_decay_rate":        self._sens_asp_decay,
            "win_rate_decay_rate":   self._sens_win_rate_decay,
            "asp_floor":             self._sens_asp_floor,
            "win_rate_floor":        self._sens_win_rate_floor,
        }
        handler = handlers.get(lever_name)
        if handler is None:
            return None

        current_value = self._read_config_path(self.config, lever_cfg.get("config_path", ""))
        if current_value is None:
            return None
        current_value = float(current_value)
        bound_value = self._calc_bound(current_value, lever_cfg)
        if bound_value is None or abs(bound_value - current_value) < 1e-12:
            return None

        return handler(
            lever_name, lever_cfg,
            current_value, bound_value,
            results, capacity, actual_bookings,
            sao_shadow_price, total_missed_saos,
        )

    # ── AE capacity lever estimators ──────────────────────────────

    def _sens_additional_hc(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Adding tenured AEs at period start.

        Each additional AE delivers:
            productivity_per_ae × (1 - avg_shrinkage) × 12 months SAOs/year
        Capped by total_missed_saos (can't recover more than demand shortfall).
        """
        productivity = self.config.get("ae_model", {}).get("productivity_per_ae", 45)
        avg_shrinkage = self._avg_shrinkage(capacity)
        delta_hc = abs(bound - cur)
        additional_saos = delta_hc * productivity * (1 - avg_shrinkage) * 12
        gain = min(additional_saos, missed_saos) * shadow
        mechanism = (
            f"+{delta_hc:.0f} tenured AEs × {productivity} SAOs/mo × "
            f"(1 − {avg_shrinkage:.0%} shrinkage) × 12 months = "
            f"+{additional_saos:,.0f} SAOs → +${gain / 1e6:.1f}M bookings"
        )
        business_context = (
            f"Each tenured AE generates ~{productivity} sales-accepted opportunities per month "
            f"at full productivity. Adding headcount directly expands your SAO supply, "
            f"which is the binding constraint in capacity-limited months. "
            f"Impact is capped by your current demand shortfall — hiring beyond that has no effect."
        )
        return self._make_result(name, cfg, cur, bound, gain, bookings, mechanism, business_context)

    def _sens_ramp_duration(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Reducing ramp time lets new hires reach full productivity sooner.

        Savings = Σ_cohort (days_saved / 30) × 0.5 × productivity_per_ae
        The 0.5 factor is the average productivity gain during the saved ramp days
        (linear ramp: goes from 0→100%, so saved days average 50% productivity).
        """
        productivity = self.config.get("ae_model", {}).get("productivity_per_ae", 45)
        avg_shrinkage = self._avg_shrinkage(capacity)
        hiring_plan = self.config.get("ae_model", {}).get("hiring_plan", [])
        total_new_hires = sum(t.get("count", 0) for t in hiring_plan)
        days_saved = abs(cur - bound)
        months_saved_per_hire = (days_saved / 30) * 0.5  # avg productivity during saved period
        additional_saos = total_new_hires * months_saved_per_hire * productivity * (1 - avg_shrinkage)
        gain = min(additional_saos, missed_saos) * shadow
        mechanism = (
            f"Ramp: {cur:.0f}d → {bound:.0f}d saves {days_saved:.0f} days × "
            f"{total_new_hires} new hires × 50% avg productivity = "
            f"+{additional_saos:,.0f} SAOs → +${gain / 1e6:.1f}M bookings"
        )
        business_context = (
            f"Ramp duration is the time a new AE takes to reach full productivity. "
            f"During ramp they generate fewer SAOs — modelled as linear from 0% to 100%. "
            f"Cutting ramp time means each of your {total_new_hires} planned new hires "
            f"contributes productive SAOs sooner. Tactics: structured onboarding, "
            f"dedicated deal coaching, or faster territory assignment."
        )
        return self._make_result(name, cfg, cur, bound, gain, bookings, mechanism, business_context)

    def _sens_backfill_delay(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Faster backfill recovers productive months lost when an AE departs.

        For each departure, reducing delay by M months recovers:
            M months × productivity × (1 - shrinkage) SAOs
        """
        productivity = self.config.get("ae_model", {}).get("productivity_per_ae", 45)
        avg_shrinkage = self._avg_shrinkage(capacity)
        annual_rate = self.config.get("ae_model", {}).get("attrition", {}).get("annual_rate", 0.1)
        starting_hc = self.config.get("ae_model", {}).get("starting_hc", 100)
        annual_departures = starting_hc * annual_rate
        months_saved = abs(cur - bound)
        additional_saos = annual_departures * months_saved * productivity * (1 - avg_shrinkage)
        gain = min(additional_saos, missed_saos) * shadow
        mechanism = (
            f"Backfill: {cur:.0f}mo → {bound:.0f}mo × {annual_departures:.0f} annual "
            f"departures × {productivity} SAOs/mo = "
            f"+{additional_saos:,.0f} SAOs → +${gain / 1e6:.1f}M bookings"
        )
        business_context = (
            f"Backfill delay is the gap between an AE departing and their replacement "
            f"becoming productive. With ~{annual_departures:.0f} expected departures this year, "
            f"every month of delay is a month of lost SAO capacity. "
            f"Reducing this requires pre-built candidate pipelines and faster offer-to-start cycles."
        )
        return self._make_result(name, cfg, cur, bound, gain, bookings, mechanism, business_context)

    def _sens_mentoring_overhead(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Reducing per-mentee overhead frees tenured AE time.

        Freed capacity = Σ_month tenured_hc × ramping_hc × Δoverhead × productivity
        """
        productivity = self.config.get("ae_model", {}).get("productivity_per_ae", 45)
        delta_overhead = abs(cur - bound)  # fraction

        freed_saos = 0.0
        for _, row in capacity.iterrows():
            tenured = row.get("hc_tenured", 0)
            ramping = row.get("hc_ramping", 0)
            freed_saos += tenured * ramping * delta_overhead * productivity / 12

        gain = min(freed_saos, missed_saos) * shadow
        mechanism = (
            f"Mentoring: {cur:.0%} → {bound:.0%} per mentee saves "
            f"{delta_overhead:.0%} of tenured time per new hire → "
            f"+{freed_saos:,.0f} SAOs → +${gain / 1e6:.1f}M bookings"
        )
        business_context = (
            f"Mentoring overhead is the fraction of a tenured AE's time consumed "
            f"per new hire they're coaching. At {cur:.0%} per mentee, every senior AE "
            f"managing a new hire loses that share of their selling capacity. "
            f"Reducing it (e.g., through structured buddy programmes or group onboarding) "
            f"frees tenured AEs to generate more SAOs."
        )
        return self._make_result(name, cfg, cur, bound, gain, bookings, mechanism, business_context)

    def _sens_shrinkage(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Reducing PTO or admin shrinkage gives AEs more selling time.

        ΔSAOs = Σ_month total_hc × Δshrinkage × productivity
        """
        productivity = self.config.get("ae_model", {}).get("productivity_per_ae", 45)
        delta_shrinkage = abs(cur - bound)
        label = cfg.get("label", name)

        total_hc_months = capacity["hc_total"].sum() if "hc_total" in capacity.columns else 0
        additional_saos = total_hc_months * delta_shrinkage * productivity
        gain = min(additional_saos, missed_saos) * shadow
        mechanism = (
            f"{label}: {cur:.0%} → {bound:.0%} × {total_hc_months:.0f} total HC-months × "
            f"{productivity} SAOs/mo = +{additional_saos:,.0f} SAOs → +${gain / 1e6:.1f}M bookings"
        )
        business_context = (
            f"Shrinkage is the percentage of an AE's working time lost to non-selling activity "
            f"({label.lower()} in this case). At {cur:.0%}, roughly {cur * 40:.0f} hours per AE "
            f"per week is unavailable for pipeline generation. Each percentage point recovered "
            f"across your full team unlocks meaningful additional SAO capacity."
        )
        return self._make_result(name, cfg, cur, bound, gain, bookings, mechanism, business_context)

    # ── Cash cycle lever ───────────────────────────────────────────

    def _sens_cash_cycle(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Shifting deals 1 month earlier moves deferred bookings into the planning window.

        Gain = amount currently classified as deferred but within 1 month of the horizon.
        This is: P(delay = horizon + 1 month) × segment bookings for late SAO months.
        """
        cash_cycle_deferral = 0.0
        if "projected_bookings" in results.columns and "in_window_bookings" in results.columns:
            cash_cycle_deferral = (
                results["projected_bookings"].sum() - results["in_window_bookings"].sum()
            )

        # Fraction that would be pulled in-window with 1 month acceleration
        # Approximation: typically 30-50% of deferred bookings are "1 month out"
        pull_in_fraction = 0.4  # conservative estimate
        gain = cash_cycle_deferral * pull_in_fraction
        mechanism = (
            f"Accelerate close by 1 month → pulls ~{pull_in_fraction:.0%} of "
            f"${cash_cycle_deferral / 1e6:.1f}M deferred bookings into the window → "
            f"+${gain / 1e6:.1f}M"
        )
        business_context = (
            f"Cash cycle deferral is the portion of bookings that fall outside the planning "
            f"horizon because payment or contract execution is delayed past year-end. "
            f"Currently ${cash_cycle_deferral / 1e6:.1f}M is deferred this way. "
            f"Accelerating close cycles — e.g., earlier commercial terms, pre-approved "
            f"discounting authority, or Q4 deal sprints — can pull a portion of this into "
            f"the current period. Estimated recovery is conservative ({pull_in_fraction:.0%} of deferred)."
        )
        return self._make_result(name, cfg, 0, -1, gain, bookings, mechanism, business_context)

    # ── Economics lever estimators ─────────────────────────────────

    def _sens_asp_decay(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Slowing ASP decay rate preserves more revenue per SAO at high volume.

        For each segment:
            ΔASP_s = asp_at_volume(vol, bound_rate) - asp_at_volume(vol, cur_rate)
            Δbookings_s = ΔASP_s × SAOs_s × CW_rate_s × IWF_s
        """
        threshold = self.config.get("economics", {}).get("default_decay", {}).get("asp", {}).get("threshold", 340)
        floor_mult = self.config.get("economics", {}).get("default_decay", {}).get("asp", {}).get("floor_multiplier", 0.75)

        total_gain = 0.0
        for _, row in results.iterrows():
            seg = row.get("segment_key", row.get("segment", ""))
            saos = row.get("required_saos", 0)
            base_asp = row.get("effective_asp", 0) / max(0.001,
                self._exp_decay_factor(saos, cur, threshold, floor_mult))
            asp_cur = base_asp * self._exp_decay_factor(saos, cur, threshold, floor_mult)
            asp_new = base_asp * self._exp_decay_factor(saos, bound, threshold, floor_mult)
            cw = row.get("effective_cw_rate", 0)
            iwf = row.get("in_window_factor", 1.0)
            total_gain += (asp_new - asp_cur) * saos * cw * iwf

        total_gain = max(0, total_gain)
        mechanism = (
            f"ASP decay rate: {cur:.4f} → {bound:.4f} "
            f"(slower decay preserves higher ASP at volume) → +${total_gain / 1e6:.1f}M bookings"
        )
        pct_drop_cur = (1 - math.exp(-cur * threshold)) * 100
        pct_drop_new = (1 - math.exp(-bound * threshold)) * 100
        business_context = (
            f"ASP decay rate controls how fast average deal size erodes as you push more "
            f"opportunities through a segment. It follows an exponential curve: "
            f"at the current rate of {cur:.4f}, ASP has already compressed by "
            f"~{pct_drop_cur:.0f}% at the segment's volume threshold. "
            f"Reducing the rate to {bound:.4f} limits that compression to ~{pct_drop_new:.0f}%. "
            f"In practice this means enforcing pricing discipline — fewer ad-hoc discounts, "
            f"stronger commercial terms, or redirecting high-volume low-margin deals."
        )
        return self._make_result(name, cfg, cur, bound, total_gain, bookings, mechanism, business_context)

    def _sens_win_rate_decay(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Slowing win-rate decay preserves close rate at high volume.

        For each segment:
            ΔCW_s = cw_at_volume(vol, bound_rate) - cw_at_volume(vol, cur_rate)
            Δbookings_s = ΔCW_s × SAOs_s × ASP_s × IWF_s
        """
        threshold = self.config.get("economics", {}).get("default_decay", {}).get("win_rate", {}).get("threshold", 260)
        floor_mult = self.config.get("economics", {}).get("default_decay", {}).get("win_rate", {}).get("floor_multiplier", 0.80)

        total_gain = 0.0
        for _, row in results.iterrows():
            saos = row.get("required_saos", 0)
            base_cw = row.get("effective_cw_rate", 0) / max(0.001,
                self._linear_decay_factor(saos, cur, threshold, floor_mult))
            cw_cur = base_cw * self._linear_decay_factor(saos, cur, threshold, floor_mult)
            cw_new = base_cw * self._linear_decay_factor(saos, bound, threshold, floor_mult)
            asp = row.get("effective_asp", 0)
            iwf = row.get("in_window_factor", 1.0)
            total_gain += (cw_new - cw_cur) * saos * asp * iwf

        total_gain = max(0, total_gain)
        mechanism = (
            f"Win-rate decay rate: {cur:.4f} → {bound:.4f} "
            f"(slower decay preserves CW rate at volume) → +${total_gain / 1e6:.1f}M bookings"
        )
        drop_cur = cur * threshold * 100
        drop_new = bound * threshold * 100
        business_context = (
            f"Win-rate decay rate captures the linear erosion of your close rate as volume "
            f"increases in a segment — modelling the reality that chasing more deals means "
            f"lower-quality ones enter the funnel. At rate {cur:.4f}, close rate drops by "
            f"~{drop_cur:.0f}pp across the volume range. Reducing to {bound:.4f} limits "
            f"that drop to ~{drop_new:.0f}pp. Levers: tighter ICP qualification, "
            f"better discovery scoring, or dedicated deal desk support at scale."
        )
        return self._make_result(name, cfg, cur, bound, total_gain, bookings, mechanism, business_context)

    def _sens_asp_floor(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Raising the ASP floor gives a guaranteed minimum price even at very high volume.

        Gain = for segments where effective_asp < bound × base_asp:
            Δbookings = (bound × base_asp - effective_asp) × SAOs × CW × IWF
        """
        total_gain = 0.0
        for _, row in results.iterrows():
            saos = row.get("required_saos", 0)
            asp_cur = row.get("effective_asp", 0)
            # Estimate base_asp: if floor is currently binding,
            # base_asp ≈ asp_cur / cur_floor
            base_asp_est = asp_cur / max(cur, 0.01)
            asp_floor_new = base_asp_est * bound
            if asp_floor_new > asp_cur:
                cw = row.get("effective_cw_rate", 0)
                iwf = row.get("in_window_factor", 1.0)
                total_gain += (asp_floor_new - asp_cur) * saos * cw * iwf

        total_gain = max(0, total_gain)
        mechanism = (
            f"ASP floor: {cur:.0%} → {bound:.0%} of baseline "
            f"(prevents ASP from compressing below this at any volume) → +${total_gain / 1e6:.1f}M bookings"
        )
        business_context = (
            f"The ASP floor is the hard minimum deal size as a percentage of your baseline "
            f"price — a contractual or policy floor below which sales cannot go regardless "
            f"of volume. Currently set at {cur:.0%} of baseline, meaning deals in high-volume "
            f"segments can compress all the way to {cur:.0%} of full price before being blocked. "
            f"Raising this to {bound:.0%} directly lifts revenue in every segment currently "
            f"at or near the floor. This is the highest-leverage pricing governance lever."
        )
        return self._make_result(name, cfg, cur, bound, total_gain, bookings, mechanism, business_context)

    def _sens_win_rate_floor(
        self, name, cfg, cur, bound, results, capacity, bookings,
        shadow, missed_saos,
    ) -> LeverSensitivity:
        """
        Raising the win-rate floor — same logic as ASP floor but for CW rate.
        """
        total_gain = 0.0
        for _, row in results.iterrows():
            saos = row.get("required_saos", 0)
            cw_cur = row.get("effective_cw_rate", 0)
            base_cw_est = cw_cur / max(cur, 0.01)
            cw_floor_new = base_cw_est * bound
            if cw_floor_new > cw_cur:
                asp = row.get("effective_asp", 0)
                iwf = row.get("in_window_factor", 1.0)
                total_gain += (cw_floor_new - cw_cur) * saos * asp * iwf

        total_gain = max(0, total_gain)
        mechanism = (
            f"Win-rate floor: {cur:.0%} → {bound:.0%} of baseline "
            f"(guarantees minimum close rate at any volume) → +${total_gain / 1e6:.1f}M bookings"
        )
        business_context = (
            f"The win-rate floor is the minimum close rate guaranteed regardless of how "
            f"much volume is pushed through a segment. At the current floor of {cur:.0%} "
            f"of baseline, close rates can decay down to {cur:.0%} before being floored. "
            f"Raising to {bound:.0%} means the team cannot accept deals they are less likely "
            f"than {bound:.0%} relative close rate to win. "
            f"This is essentially a funnel quality gate — fewer but higher-probability deals."
        )
        return self._make_result(name, cfg, cur, bound, total_gain, bookings, mechanism, business_context)

    # ── Decay function helpers ─────────────────────────────────────

    @staticmethod
    def _exp_decay_factor(volume: float, rate: float, threshold: float, floor_mult: float) -> float:
        """Exponential decay factor: f = exp(-rate × max(0, vol - threshold)), floored."""
        excess = max(0, volume - threshold)
        return max(floor_mult, math.exp(-rate * excess))

    @staticmethod
    def _linear_decay_factor(volume: float, rate: float, threshold: float, floor_mult: float) -> float:
        """Linear decay factor: f = max(floor, 1 - rate × max(0, vol - threshold))."""
        excess = max(0, volume - threshold)
        return max(floor_mult, 1.0 - rate * excess)

    # ── Shared utilities ───────────────────────────────────────────

    def _avg_shrinkage(self, capacity: pd.DataFrame) -> float:
        """Average effective shrinkage rate across months."""
        if "shrinkage_rate" in capacity.columns and len(capacity) > 0:
            return float(capacity["shrinkage_rate"].mean())
        # Fallback: sum of PTO + admin from config
        shrink_cfg = self.config.get("ae_model", {}).get("shrinkage", {})
        return (shrink_cfg.get("pto_pct", 0.08)
                + shrink_cfg.get("admin_pct", 0.05)
                + shrink_cfg.get("enablement_base_pct", 0.03))

    def _make_result(
        self,
        lever_name: str,
        cfg: dict,
        cur: float,
        bound: float,
        gain: float,
        actual_bookings: float,
        mechanism: str,
        business_context: str = "",
    ) -> LeverSensitivity:
        label = cfg.get("label", lever_name)
        unit = cfg.get("unit", "")
        direction = cfg.get("direction", "")
        annual_target = self.config.get("targets", {}).get("annual_target", 0)
        gap = annual_target - actual_bookings

        return LeverSensitivity(
            lever_name=lever_name,
            label=label,
            category=cfg.get("category", ""),
            unit=unit,
            current_value=cur,
            bound_value=bound,
            direction=direction,
            estimated_gain=gain,
            gain_pct_of_gap=(gain / gap * 100) if gap > 0 else 0.0,
            gain_pct_of_base=(gain / actual_bookings * 100) if actual_bookings > 0 else 0.0,
            business_context=business_context,
            mechanism=mechanism,
            recommendation=self._format_rec(label, cur, bound, unit, gain, actual_bookings),
        )

    @staticmethod
    def _format_rec(
        label: str, cur: float, bound: float, unit: str, gain: float,
        actual_bookings: float = 0.0,
    ) -> str:
        def fmt(v: float) -> str:
            if unit == "%":
                return f"{v * 100:.0f}%"
            if unit == "rate":
                return f"{v:.4f}"
            if unit == "multiplier":
                return f"{v:.2f}"
            return f"{v:.0f}" if v == int(v) else f"{v:.2f}"
        sign = "+" if gain >= 0 else ""
        pct_str = ""
        if actual_bookings > 0:
            pct_str = f"  ({sign}{gain / actual_bookings * 100:.1f}% of base bookings)"
        return (
            f"{label}: {fmt(cur)} → {fmt(bound)} {unit}  "
            f"→  {sign}${gain / 1e6:.1f}M bookings{pct_str}"
        )

    def _read_config_path(self, config: dict, path: str):
        keys = path.split(".")
        cur = config
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        return cur

    def _calc_bound(self, current: float, cfg: dict) -> Optional[float]:
        direction = cfg.get("direction", "increase")
        if direction == "decrease":
            mv = cfg.get("min_value")
            if mv is not None:
                return float(mv)
            md = cfg.get("max_delta")
            if md is not None:
                return current - float(md)
        else:
            mv = cfg.get("max_value")
            if mv is not None:
                return float(mv)
            md = cfg.get("max_delta")
            if md is not None:
                return current + float(md)
        return None

    # ── Narrative & output ─────────────────────────────────────────

    def _build_narrative(
        self,
        gap: float,
        annual_target: float,
        actual_bookings: float,
        decomp: GapDecomposition,
        levers: List[LeverSensitivity],
    ) -> str:
        lines = []
        L = lines.append

        L("=" * 70)
        L("LEVER ANALYSIS — GAP ATTRIBUTION & RECOMMENDATIONS")
        L("=" * 70)
        L("")

        # Gap headline
        if gap > 0:
            L(f"  Plan misses target by ${gap / 1e6:.1f}M  "
              f"({gap / annual_target * 100:.1f}% of ${annual_target / 1e6:.0f}M target)")
        else:
            L(f"  Plan EXCEEDS target by ${abs(gap) / 1e6:.1f}M — upside potential shown below.")
        L(f"  Projected bookings: ${actual_bookings / 1e6:.1f}M   Target: ${annual_target / 1e6:.0f}M")
        L("")

        # Waterfall decomposition
        L("GAP DECOMPOSITION — where the gap comes from")
        L("-" * 70)
        L(f"  Baseline (zero decay, no capacity constraint)  ${decomp.baseline_bookings / 1e6:.1f}M")
        L(f"  − Capacity shortfall (demand > supply)         −${decomp.capacity_shortfall_loss / 1e6:.1f}M")
        L(f"  − ASP decay at volume                          −${decomp.asp_decay_loss / 1e6:.1f}M")
        L(f"  − Win-rate decay at volume                     −${decomp.win_rate_decay_loss / 1e6:.1f}M")
        L(f"  − Cash cycle deferral (outside horizon)        −${decomp.cash_cycle_deferral / 1e6:.1f}M")
        L(f"  = Projected bookings                            ${decomp.actual_bookings / 1e6:.1f}M")
        L(f"  − Annual target                                −${annual_target / 1e6:.0f}M")
        L(f"  = Gap                                          −${max(0, decomp.gap) / 1e6:.1f}M")
        L("")

        # Primary driver
        losses = {
            "Capacity constraint": decomp.capacity_shortfall_loss,
            "ASP decay":           decomp.asp_decay_loss,
            "Win-rate decay":      decomp.win_rate_decay_loss,
            "Cash cycle deferral": decomp.cash_cycle_deferral,
        }
        biggest = max(losses, key=losses.get)
        L(f"  Primary driver of gap: {biggest} (${losses[biggest] / 1e6:.1f}M)")
        L("")

        # Ranked recommendations
        positive = [r for r in levers if r.estimated_gain > 1e3]
        if positive:
            L("RECOMMENDED LEVERS (ranked by estimated bookings impact)")
            L("-" * 70)
            cumulative = 0.0
            gap_closed = False
            for i, r in enumerate(positive, 1):
                cumulative += r.estimated_gain
                L(f"  {i}. {r.recommendation}")
                L(f"     Impact:  +{r.gain_pct_of_base:.1f}% of base bookings  "
                  f"|  closes {r.gain_pct_of_gap:.0f}% of gap  "
                  f"|  cumulative: +${cumulative / 1e6:.1f}M")
                if r.business_context:
                    # Wrap context to 66 chars so it prints cleanly at indent level
                    words = r.business_context.split()
                    line, wrapped = [], []
                    for w in words:
                        if sum(len(x) + 1 for x in line) + len(w) > 66:
                            wrapped.append("     " + " ".join(line))
                            line = [w]
                        else:
                            line.append(w)
                    if line:
                        wrapped.append("     " + " ".join(line))
                    L(f"     What this means:")
                    for wl in wrapped:
                        L(wl)
                L(f"     How it's calculated:  {r.mechanism}")
                if gap > 0 and cumulative >= gap and not gap_closed:
                    L(f"     >>> Gap closed at this point <<<")
                    gap_closed = True
                L("")

            total_upside = sum(r.estimated_gain for r in positive)
            L(f"  Maximum upside (all levers): +${total_upside / 1e6:.1f}M")
            if gap > 0:
                if total_upside >= gap:
                    L(f"  Gap CAN be closed by combining the levers above.")
                else:
                    shortfall = gap - total_upside
                    L(f"  Gap CANNOT be fully closed analytically.")
                    L(f"  Residual shortfall even at max lever movement: ${shortfall / 1e6:.1f}M")
                    L(f"  Consider: revising annual target, new market entry, or product expansion.")
        else:
            L("  No levers produced meaningful bookings impact.")
        L("")

        no_impact = [r for r in levers if abs(r.estimated_gain) <= 1e3]
        if no_impact:
            L("NEGLIGIBLE IMPACT LEVERS")
            L("-" * 70)
            for r in no_impact:
                L(f"  − {r.label}: moving to bound has <$1K estimated impact")
            L("")

        L("=" * 70)
        L("NOTE: All estimates are first-order analytical approximations.")
        L("Combining multiple levers may have compounding or offsetting effects.")
        L("Validate top 1-2 levers by running --mode what-if before committing.")
        L("=" * 70)
        return "\n".join(lines)

    @staticmethod
    def _to_dataframe(levers: List[LeverSensitivity], gap: float) -> pd.DataFrame:
        if not levers:
            return pd.DataFrame()
        rows = [
            {
                "rank": i + 1,
                "lever": r.label,
                "category": r.category,
                "current_value": r.current_value,
                "recommended_value": r.bound_value,
                "unit": r.unit,
                "estimated_gain_$": round(r.estimated_gain, 0),
                "pct_of_gap_closed": round(r.gain_pct_of_gap, 1),
                "pct_of_base_bookings": round(r.gain_pct_of_base, 2),
                "recommendation": r.recommendation,
            }
            for i, r in enumerate(levers)
        ]
        return pd.DataFrame(rows)
