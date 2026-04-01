"""
================================================================================
Allocation Optimizer Module (Module 6)
================================================================================

The core engine: determines how SAOs (Sales Accepted Opportunities) are
distributed across product-channel segments to meet revenue targets, subject
to constraints on share, capacity, and economics.

THEORY:
-------
The optimizer solves a constrained allocation problem:
    Given:
        - Revenue target for a period T_p
        - Effective ROI curves (ASP × CW Rate) for each segment, possibly declining
          with volume (due to market saturation, AE learning, competitive response)
        - Constraints: min/max share per segment, total share = 1.0
        - Capacity limit: total SAOs available in the period

    Find:
        - Share allocation s = [s_1, s_2, ..., s_n] that maximizes some objective
          (bookings, pipeline, or custom metric)
        - Total SAOs required = T_p / weighted_avg_ROI(s)
        - Per-segment SAOs = s_i × total_SAOs

Two modes are supported:

1. GREEDY MODE (default, recommended for production)
   - Fast, explainable, deterministic
   - Allocates in small steps (0.01 increments of remaining share)
   - After each step, re-evaluates marginal ROI for all segments
   - Respects diminishing returns: allocates preferentially to segments
     where marginal ROI is highest
   - This is an enhanced version of the original case study algorithm,
     where the key improvement is step-by-step re-evaluation instead of
     sort-once-and-fill
   - Complexity: O(n × steps) per period, typically very fast

2. SOLVER MODE (precise, for complex scenarios)
   - Uses scipy.optimize.minimize with SLSQP method
   - Handles non-linear decay curves with precision
   - Warm-starts from greedy solution for speed
   - More compute-intensive but optimal when decay curves interact
   - Useful when you want to prove optimality or handle very complex constraints
   - Complexity: O(n²) per iteration, typically 10-50 iterations

WORKFLOW (per period):
------
1. Load period target, active segments, base data
2. Initialize: assign share_floor to every segment, mark remaining share
3. [GREEDY ONLY] Begin iterative allocation loop:
   - For each small allocation step:
     a. Calculate current volume for each segment = s_i × total_SAOs_estimate
     b. Get effective ROI at that volume for each segment (via economics engine)
     c. Find segment with highest marginal ROI that hasn't hit ceiling
     d. Allocate the step to that segment
     e. If all remaining segments at ceiling, stop
4. [SOLVER ONLY] Set up optimization problem:
   - Objective: maximize weighted bookings (or pipeline/custom)
   - Constraints: share bounds, sum=1, capacity limit
   - Warm start: greedy solution
   - Solve using scipy.optimize.minimize
5. Calculate final metrics:
   - Weighted avg ROI = Σ(s_i × ROI_at_volume_i)
   - Total SAOs = T_period / weighted_avg_ROI
   - Per-segment: SAOs, pipeline, bookings, deals
6. Check capacity constraint:
   - If total_SAOs > capacity_limit: flag as constrained, adjust bookings
   - Otherwise: all projections are at plan

OUTPUT (per period):
----
DataFrame with one row per segment, columns:
    - month (or period)
    - product, channel, (other active dims)
    - share: allocated share [0, 1]
    - required_saos: total SAOs needed for target at this share
    - effective_asp: weighted avg ASP at this share level
    - effective_cw_rate: weighted avg CW rate at this share level
    - projected_pipeline: SAOs × ASP
    - projected_bookings: SAOs × ASP × CW_rate
    - projected_deals: ROUND(bookings / ASP)
    - capacity_flag: 1 if constrained by capacity, 0 otherwise
    - weighted_roi: effective ROI at this volume level

"""

import pandas as pd
import numpy as np
from scipy.optimize import minimize
from typing import Optional, Callable, Dict, Tuple, List
import logging

logger = logging.getLogger(__name__)


class AllocationOptimizer:
    """
    Core optimization engine for SAO allocation.

    Determines how to distribute sales capacity (SAOs) across product-channel
    segments to meet revenue targets, accounting for diminishing returns and
    operational constraints.

    Two modes:
    - 'greedy': Fast, explainable. Allocates iteratively by marginal ROI.
    - 'solver': Uses scipy.optimize.minimize for precise constrained optimization.

    Attributes:
        config (dict): Configuration dictionary with keys:
            - allocation.objective.metric: "bookings", "pipeline", or custom function
            - allocation.constraints.share_floor: minimum share per segment
            - allocation.constraints.share_ceiling: maximum share per segment
            - allocation.optimizer_mode: "greedy" or "solver"
            - system.solver.*: scipy solver parameters
        mode (str): "greedy" or "solver"
        objective_metric (str): "bookings" or "pipeline"
        share_floor (float): Minimum share per segment
        share_ceiling (float): Maximum share per segment
        step_size (float): Allocation step for greedy mode (e.g., 0.01 = 1%)
        solver_config (dict): Parameters for scipy.optimize.minimize
    """

    def __init__(self, config: dict):
        """
        Initialize the optimizer with configuration.

        Args:
            config (dict): Configuration dictionary containing:
                - allocation.objective.metric
                - allocation.constraints.share_floor
                - allocation.constraints.share_ceiling
                - allocation.optimizer_mode
                - system.solver parameters

        Raises:
            ValueError: If config is missing required keys or has invalid values.
        """
        self.config = config

        # Parse allocation config
        alloc_cfg = config.get("allocation", {})
        self.objective_metric = alloc_cfg.get("objective", {}).get("metric", "bookings")
        self.objective_direction = alloc_cfg.get("objective", {}).get("direction", "maximize")

        constraints = alloc_cfg.get("constraints", {})
        self.share_floor = constraints.get("share_floor", 0.05)
        self.share_ceiling = constraints.get("share_ceiling", 0.40)

        self.mode = alloc_cfg.get("optimizer_mode", "greedy")
        if self.mode not in ["greedy", "solver"]:
            raise ValueError(f"optimizer_mode must be 'greedy' or 'solver', got {self.mode}")

        # Greedy-specific
        self.step_size = 0.01  # 1% increments per allocation step

        # Solver-specific
        sys_cfg = config.get("system", {})
        solver_cfg = sys_cfg.get("solver", {}) if isinstance(sys_cfg, dict) else {}
        self.solver_config = {
            "method": solver_cfg.get("method", "SLSQP"),
            "max_iterations": int(solver_cfg.get("max_iterations", 1000)),
            "convergence_tolerance": float(solver_cfg.get("convergence_tolerance", 1e-8)),
        }

        # Cash cycle awareness
        cash_cycle_cfg = config.get("economics", {}).get("cash_cycle", {})
        if isinstance(cash_cycle_cfg, dict):
            self.cash_cycle_enabled = cash_cycle_cfg.get("enabled", False)
        else:
            self.cash_cycle_enabled = False

        logger.info(f"AllocationOptimizer initialized: mode={self.mode}, "
                    f"objective={self.objective_metric}, "
                    f"share_floor={self.share_floor}, share_ceiling={self.share_ceiling}, "
                    f"cash_cycle={'ON' if self.cash_cycle_enabled else 'OFF'}")

    def optimize(self,
                 targets: pd.DataFrame,
                 base_data: pd.DataFrame,
                 economics_engine: Optional[object] = None,
                 capacity: pd.DataFrame = None) -> pd.DataFrame:
        """
        Run the full optimization across all periods.

        This is the main entry point. It calls the appropriate optimization method
        (greedy or solver) for each period and assembles the results.

        Args:
            targets (pd.DataFrame):
                DataFrame with columns [period/month, target_revenue].
                From TargetGenerator.
                Example:
                    month   target_revenue
                    1       15660000
                    2       18160000
                    ...

            base_data (pd.DataFrame):
                Clean segment-level data with columns:
                [month, product, channel, (other active dims),
                 asp, close_win_rate, deals_historical, ...]
                From DataLoader. Used to get base ASP and CW rate per segment.

            economics_engine (optional):
                EconomicsEngine object with method:
                    get_effective_roi(segment_str, volume, current_asp, current_cw)
                    → (effective_asp, effective_cw, roi)
                If None, optimizer uses base ASP and CW rate (no decay).

            capacity (pd.DataFrame, optional):
                DataFrame with columns [month, effective_capacity_saos].
                From AECapacityModel. If provided, enforces SAO capacity limit.
                If None, optimization is unconstrained on SAO volume.

        Returns:
            pd.DataFrame:
                Allocation results with columns:
                    - month (or active period column)
                    - product, channel, (other active dims)
                    - share: allocated share [0, 1]
                    - required_saos: SAOs needed for target
                    - effective_asp: weighted avg ASP
                    - effective_cw_rate: weighted avg CW rate
                    - projected_pipeline: SAOs × ASP
                    - projected_bookings: SAOs × ASP × CW_rate
                    - projected_deals: bookings / ASP
                    - capacity_flag: 1 if constrained, 0 otherwise
                    - weighted_roi: effective ROI at allocated volume

        Raises:
            ValueError: If targets or base_data are empty or malformed.
        """
        if targets.empty:
            raise ValueError("targets DataFrame is empty")
        if base_data.empty:
            raise ValueError("base_data DataFrame is empty")

        logger.info(f"Starting optimization across {len(targets)} period(s)")

        # Identify period column in targets (assume first column is period identifier)
        period_col = targets.columns[0]
        periods = targets[period_col].unique()

        # Find the matching period column in base_data
        # Try: period, month, quarter (in that order)
        period_col_base = None
        for candidate in ['period', 'month', 'quarter', period_col]:
            if candidate in base_data.columns:
                period_col_base = candidate
                break

        if period_col_base is None:
            raise ValueError(
                f"Could not find period column in base_data. "
                f"Available columns: {list(base_data.columns)}"
            )

        logger.info(f"Using period column: {period_col} (targets), {period_col_base} (base_data)")

        results_list = []

        for period in sorted(periods):
            logger.info(f"\n--- Optimizing period {period} ---")

            # Get target for this period
            period_targets = targets[targets[period_col] == period]
            target_revenue = period_targets["target_revenue"].iloc[0]

            # Get data for this period
            period_data = base_data[base_data[period_col_base] == period].copy()

            # Get capacity limit for this period (if available)
            capacity_limit = None
            if capacity is not None:
                # Find the matching period column in capacity
                period_col_cap = None
                for candidate in ['period', 'month', 'quarter', period_col]:
                    if candidate in capacity.columns:
                        period_col_cap = candidate
                        break

                if period_col_cap:
                    cap_data = capacity[capacity[period_col_cap] == period]
                    if not cap_data.empty:
                        capacity_limit = cap_data["effective_capacity_saos"].iloc[0]

            logger.info(f"Target revenue: ${target_revenue:,.0f}")
            if capacity_limit:
                logger.info(f"Capacity limit: {capacity_limit:,.0f} SAOs")
            else:
                logger.info(f"No capacity constraint")

            # Run period-specific optimization
            if self.mode == "greedy":
                period_results = self._optimize_period_greedy(
                    period_data, target_revenue, economics_engine, capacity_limit
                )
            else:  # solver mode
                period_results = self._optimize_period_solver(
                    period_data, target_revenue, economics_engine, capacity_limit
                )

            results_list.append(period_results)

        # Concatenate results across all periods
        full_results = pd.concat(results_list, ignore_index=True)

        # Log completion using the period column from base_data
        if period_col_base in full_results.columns:
            logger.info(f"\nOptimization complete. Total periods: {len(full_results[period_col_base].unique())}")
        else:
            logger.info(f"\nOptimization complete. Total rows: {len(full_results)}")

        return full_results

    def _optimize_period_greedy(self,
                                period_data: pd.DataFrame,
                                target_revenue: float,
                                economics_engine: Optional[object],
                                capacity_limit: Optional[float]) -> pd.DataFrame:
        """
        Greedy optimization for a single period.

        Algorithm (enhanced greedy with step-wise re-evaluation):

        1. Identify all active segments for this period
        2. Validate that floor × n_segments <= 1.0 (feasibility check)
        3. Initialize: assign share_floor to every segment, calculate remaining share
        4. Iterative allocation loop:
           a. Estimate total_SAOs using current segment shares and base ROI
           b. For each remaining allocation step (step_size = 0.01):
              - Calculate current volume for each segment: v_i = s_i × total_SAOs
              - Get effective ROI for each segment at current volume
                (via economics_engine if available, else use base ASP × CW)
              - Find segment with highest marginal ROI that hasn't hit ceiling
              - If found: increment that segment's share by step_size
              - If not found (all at ceiling): break inner loop
              - Update total_SAOs estimate with new weighted_avg_roi
           c. Repeat until all remaining share is allocated or max iterations
        5. Calculate final metrics:
           - weighted_avg_roi = Σ(s_i × roi_i)
           - total_saos = target_revenue / weighted_avg_roi
           - per_segment metrics (pipeline, bookings, deals)
        6. Capacity check:
           - If total_saos > capacity_limit: set capacity_flag=1,
             adjust bookings to capacity_limit × roi
           - Otherwise: capacity_flag=0
        7. Assemble output DataFrame

        Args:
            period_data (pd.DataFrame): Data for this period only.
            target_revenue (float): Target bookings for this period.
            economics_engine (optional): Economics engine for decay curves.
            capacity_limit (optional): Max SAOs for this period.

        Returns:
            pd.DataFrame: Allocation for this period.
        """
        logger.info(f"Using GREEDY optimization mode")

        # Get active dimension columns and create segment identifiers
        period_data = period_data.copy()
        active_dims = self._get_active_dimensions(period_data)

        # Create segment key
        period_data["segment_key"] = self._create_segment_key(period_data, active_dims)
        segments = period_data.groupby("segment_key").first().reset_index()

        n_segments = len(segments)
        logger.info(f"Found {n_segments} segments for allocation")

        # Feasibility check
        if self.share_floor * n_segments > 1.0:
            raise ValueError(
                f"Infeasible constraint: floor * n_segments = {self.share_floor * n_segments} > 1.0. "
                f"Reduce share_floor or increase ceiling."
            )

        # Initialize shares with floor for all segments
        shares = {seg: self.share_floor for seg in segments["segment_key"]}
        remaining_share = 1.0 - (self.share_floor * n_segments)

        logger.info(f"Initial allocation: {self.share_floor:.1%} per segment")
        logger.info(f"Remaining share to allocate: {remaining_share:.1%}")

        # Iterative allocation: allocate in steps, re-evaluating marginal ROI each step
        step_count = 0
        max_steps = int(remaining_share / self.step_size) + 100  # safety margin

        while remaining_share > self.step_size * 0.5:  # Stop when < 0.5% left
            # Estimate total SAOs using current shares
            weighted_roi = self._compute_weighted_roi(
                shares, segments, economics_engine, target_revenue
            )
            estimated_total_saos = target_revenue / weighted_roi if weighted_roi > 0 else 0

            # Find segment with highest marginal ROI that can still accept allocation
            best_segment = None
            best_marginal_roi = -np.inf

            for seg_key, current_share in shares.items():
                # Skip if at ceiling
                if current_share >= self.share_ceiling:
                    continue

                # Get segment base data
                seg_data = segments[segments["segment_key"] == seg_key].iloc[0]

                # Calculate marginal ROI at current volume
                current_volume = current_share * estimated_total_saos
                is_supersized = seg_data.get("is_supersized", False)
                effective_asp, effective_cw, marginal_roi = self._get_segment_roi(
                    seg_key, seg_data.get("asp", 0),
                    seg_data.get("close_win_rate", 0),
                    current_volume, economics_engine, is_supersized
                )

                # Cash cycle: weight marginal ROI by in-window factor so the
                # optimizer prefers shorter-cycle products in late months
                if self.cash_cycle_enabled and economics_engine is not None:
                    product = economics_engine._extract_product_from_segment(seg_key)
                    period_num = period_data.iloc[0].get("month", 1) if "month" in period_data.columns else 1
                    iwf = economics_engine.get_in_window_factor(product, period_num)
                    marginal_roi *= iwf

                if marginal_roi > best_marginal_roi:
                    best_marginal_roi = marginal_roi
                    best_segment = seg_key

            # If no segment can accept, we're done
            if best_segment is None:
                logger.debug(f"All segments at ceiling or no positive ROI remaining")
                break

            # Allocate step to best segment
            allocation = min(self.step_size, remaining_share,
                           self.share_ceiling - shares[best_segment])
            shares[best_segment] += allocation
            remaining_share -= allocation
            step_count += 1

            if step_count % 20 == 0:
                logger.debug(f"Step {step_count}: allocated {allocation:.2%} to {best_segment}, "
                           f"remaining {remaining_share:.2%}")

            if step_count > max_steps:
                logger.warning(f"Greedy allocation exceeded max_steps ({max_steps}), stopping")
                break

        logger.info(f"Greedy allocation complete: {step_count} steps")

        # Calculate final metrics and build results
        results = self._build_results_df(
            period_data, segments, shares, target_revenue, economics_engine, capacity_limit
        )

        return results

    def _optimize_period_solver(self,
                                period_data: pd.DataFrame,
                                target_revenue: float,
                                economics_engine: Optional[object],
                                capacity_limit: Optional[float]) -> pd.DataFrame:
        """
        Scipy solver optimization for a single period.

        Problem formulation:

        Decision variables:
            s = [s_1, s_2, ..., s_n] where s_i = share allocated to segment i

        Objective (to maximize bookings):
            max Σ_i [ s_i × total_SAOs × ASP_i(v_i) × CW_i(v_i) ]
            where v_i = s_i × total_SAOs
            and total_SAOs = target_revenue / Σ_i [ s_i × ROI_i(v_i) ]

        This is equivalent to (and more stable):
            max target_revenue
            subject to the constraints below

        So we can reformulate as:
            min -target_revenue  (negative for minimization)
            or equivalently
            min Σ_i [ s_i × weighted_cost ]

        Constraints:
            - s_i >= share_floor ∀ i
            - s_i <= share_ceiling ∀ i
            - Σ_i s_i = 1.0 (shares sum to 1)
            - total_SAOs <= capacity_limit (if provided)
            - Any custom per-segment constraints from config

        Warm start:
            Use greedy solution as initial guess (x0)

        Solver:
            scipy.optimize.minimize with method='SLSQP' (Sequential Least Squares Programming)
            - Handles non-linear objectives and constraints
            - Respects bounds
            - Fast for problems with 10-100 variables

        Args:
            period_data (pd.DataFrame): Data for this period.
            target_revenue (float): Target bookings.
            economics_engine (optional): Economics engine.
            capacity_limit (optional): Capacity constraint.

        Returns:
            pd.DataFrame: Optimal allocation for this period.
        """
        logger.info(f"Using SOLVER optimization mode (method={self.solver_config['method']})")

        # Get active dimensions and segments
        period_data = period_data.copy()
        active_dims = self._get_active_dimensions(period_data)
        period_data["segment_key"] = self._create_segment_key(period_data, active_dims)
        segments = period_data.groupby("segment_key").first().reset_index()

        n_segments = len(segments)
        segment_keys = segments["segment_key"].tolist()

        logger.info(f"Optimizing {n_segments} segments with scipy.optimize.minimize")

        # Warm start: use greedy solution
        x0 = np.ones(n_segments) / n_segments  # Equal allocation as fallback
        greedy_results = self._optimize_period_greedy(
            period_data, target_revenue, economics_engine, capacity_limit
        )
        if not greedy_results.empty:
            # Extract shares from greedy results
            for i, seg_key in enumerate(segment_keys):
                greedy_share = greedy_results[
                    greedy_results["segment_key"] == seg_key
                ]["share"].values
                if len(greedy_share) > 0:
                    x0[i] = greedy_share[0]

        logger.info(f"Warm start from greedy solution: {x0}")

        # Define objective function: minimize negative bookings (i.e., maximize bookings)
        def objective(shares_array):
            """Objective: maximize bookings = target_revenue. Return negative for minimization."""
            # Calculate weighted avg ROI
            weighted_roi = 0
            for i, seg_key in enumerate(segment_keys):
                share = shares_array[i]
                if share <= 0:
                    continue

                seg_data = segments[segments["segment_key"] == seg_key].iloc[0]
                base_asp = seg_data.get("asp", 0)
                base_cw = seg_data.get("close_win_rate", 0)
                is_supersized = seg_data.get("is_supersized", False)

                # Estimate volume at this share
                if weighted_roi > 0:
                    estimated_saos = target_revenue / weighted_roi
                else:
                    # Fallback: allocate minimum viable share (share_floor % of total capacity estimate)
                    share_floor = self.config.get("allocation.constraints.share_floor", 0.05)
                    # Estimate total capacity from period (use target_revenue / base ROI as proxy)
                    total_capacity = target_revenue / 1000  # Reasonable estimate
                    estimated_saos = share_floor * total_capacity
                volume = share * estimated_saos

                _, _, roi = self._get_segment_roi(
                    seg_key, base_asp, base_cw, volume, economics_engine, is_supersized
                )

                # Cash cycle: weight ROI by in-window factor for the solver
                if self.cash_cycle_enabled and economics_engine is not None:
                    product = economics_engine._extract_product_from_segment(seg_key)
                    period_num = (period_data.iloc[0].get("month", 1)
                                  if "month" in period_data.columns else 1)
                    iwf = economics_engine.get_in_window_factor(product, period_num)
                    roi *= iwf

                weighted_roi += share * roi

            # Penalize if weighted_roi is zero or negative
            if weighted_roi <= 0:
                return 1e10

            return -weighted_roi  # Negative because we minimize

        # Constraints
        constraints = []

        # Constraint 1: Σ shares = 1.0
        constraints.append({
            "type": "eq",
            "fun": lambda x: np.sum(x) - 1.0
        })

        # Constraint 2: Total SAOs <= capacity (if provided)
        if capacity_limit is not None:
            def capacity_constraint(shares_array):
                weighted_roi = self._compute_weighted_roi(
                    {segment_keys[i]: shares_array[i] for i in range(n_segments)},
                    segments, economics_engine, target_revenue
                )
                if weighted_roi <= 0:
                    return -capacity_limit  # Infeasible
                total_saos = target_revenue / weighted_roi
                return capacity_limit - total_saos  # <= 0 when infeasible

            constraints.append({
                "type": "ineq",
                "fun": capacity_constraint
            })

        # Bounds: floor <= s_i <= ceiling
        bounds = [(self.share_floor, self.share_ceiling) for _ in range(n_segments)]

        # Solve
        result = minimize(
            objective,
            x0,
            method=self.solver_config["method"],
            bounds=bounds,
            constraints=constraints,
            options={
                "maxiter": self.solver_config["max_iterations"],
                "ftol": self.solver_config["convergence_tolerance"],
            }
        )

        if result.success:
            logger.info(f"Solver converged: {result.message}")
            optimal_shares = {segment_keys[i]: result.x[i] for i in range(n_segments)}
        else:
            logger.warning(f"Solver did not converge: {result.message}. Using greedy solution.")
            optimal_shares = {segment_keys[i]: x0[i] for i in range(n_segments)}

        # Build results with optimal shares
        results = self._build_results_df(
            period_data, segments, optimal_shares, target_revenue, economics_engine, capacity_limit
        )

        return results

    def _get_segment_roi(self,
                        segment_key: str,
                        base_asp: float,
                        base_cw: float,
                        volume: float,
                        economics_engine: Optional[object],
                        is_supersized: bool = False) -> Tuple[float, float, float]:
        """
        Get effective ASP, CW rate, and ROI for a segment at a given volume.

        If economics_engine is None, returns base values (no decay).
        If economics_engine is provided, applies decay/improvement curves.

        SUPERSIZED HANDLING:
        If is_supersized is True (segment had an unusually large deal that inflated ASP),
        the effective_asp is capped at base_asp. No upward ASP multipliers are applied,
        to prevent using inflated historical ASP in ROI calculations.

        Args:
            segment_key (str): Segment identifier.
            base_asp (float): Base Average Selling Price.
            base_cw (float): Base Close-Win Rate [0, 1].
            volume (float): Current SAO volume for this segment.
            economics_engine (optional): EconomicsEngine object.
            is_supersized (bool): If True, segment is oversized and ASP is capped.

        Returns:
            Tuple[float, float, float]: (effective_asp, effective_cw, roi)
                where roi = effective_asp × effective_cw

        Raises:
            ValueError: If base_asp or base_cw are negative or invalid.
        """
        if base_asp < 0 or base_cw < 0 or base_cw > 1:
            raise ValueError(
                f"Invalid base metrics for {segment_key}: "
                f"ASP={base_asp}, CW={base_cw}"
            )

        if economics_engine is None:
            # No decay: use base values as-is
            logger.warning(
                f"No economics engine provided for segment '{segment_key}' at volume {volume:.0f}. "
                f"Using base values (ASP=${base_asp:,.0f}, CW={base_cw:.1%}) with no decay applied."
            )
            effective_asp = base_asp
            effective_cw = base_cw
        else:
            # Apply decay curves
            try:
                effective_asp = economics_engine.get_effective_asp(segment_key, volume)
                effective_cw = economics_engine.get_effective_win_rate(segment_key, volume)
            except Exception as e:
                logger.warning(f"Economics engine error for {segment_key}: {e}. "
                             f"Using base values.")
                effective_asp = base_asp
                effective_cw = base_cw

        # Handle supersized segments: cap ASP at base value (no upward multipliers)
        if is_supersized and effective_asp > base_asp:
            logger.warning(f"Segment {segment_key} is supersized. Capping effective_asp "
                         f"from {effective_asp:,.2f} to base_asp {base_asp:,.2f} "
                         f"(prevents inflated ASP from historical large deal)")
            effective_asp = base_asp

        roi = effective_asp * effective_cw
        return effective_asp, effective_cw, roi

    def _compute_weighted_roi(self,
                             shares: Dict[str, float],
                             segments: pd.DataFrame,
                             economics_engine: Optional[object],
                             target_revenue: float) -> float:
        """
        Compute weighted average ROI across all segments given current shares.

        This is used to estimate total SAOs needed: SAOs = target / weighted_ROI

        Args:
            shares (dict): {segment_key: share} mapping.
            segments (pd.DataFrame): Segment data.
            economics_engine (optional): Economics engine.
            target_revenue (float): Revenue target (used to estimate SAOs).

        Returns:
            float: Weighted average ROI ($ per SAO).

        Note:
            This is a circular dependency: ROI depends on volume, volume depends on
            total SAOs, total SAOs depends on ROI. We iterate to convergence.
        """
        # Start with estimate assuming base ROI
        total_saos = target_revenue / 1000  # rough initial estimate

        for iteration in range(5):  # Usually converges in 2-3 iterations
            weighted_roi = 0

            for seg_key, share in shares.items():
                if share <= 0:
                    continue

                seg_data = segments[segments["segment_key"] == seg_key].iloc[0]
                base_asp = seg_data.get("asp", 0)
                base_cw = seg_data.get("close_win_rate", 0)
                is_supersized = seg_data.get("is_supersized", False)

                volume = share * total_saos
                _, _, roi = self._get_segment_roi(
                    seg_key, base_asp, base_cw, volume, economics_engine, is_supersized
                )
                weighted_roi += share * roi

            if weighted_roi <= 0:
                return 1.0  # Default fallback

            # Update SAO estimate
            new_total_saos = target_revenue / weighted_roi

            # Check convergence
            if abs(new_total_saos - total_saos) / (total_saos + 1) < 0.001:
                break

            total_saos = new_total_saos

        return weighted_roi

    def _get_active_dimensions(self, data: pd.DataFrame) -> List[str]:
        """
        Return active dimension columns that are both enabled in config
        and present in the supplied DataFrame.

        Authority for *which* dimensions are enabled lives exclusively in
        ConfigManager (computed once at init and cached). This method simply
        filters that cached list to columns that actually exist in the data,
        guarding against a config declaring a dimension (e.g. 'region') that
        a given data file does not contain.

        Args:
            data (pd.DataFrame): Period data for one optimisation pass.

        Returns:
            List[str]: Dimension column names to use as segment keys.
        """
        return [dim for dim in self.config.get_active_dimensions()
                if dim in data.columns]

    def _create_segment_key(self,
                           data: pd.DataFrame,
                           active_dims: List[str]) -> pd.Series:
        """
        Create segment identifiers by joining active dimension values.

        Example: if active_dims = ["product", "channel"], then
            segment_key = "CM.Marketing", "EOR.Outbound", etc.

        Args:
            data (pd.DataFrame): Data.
            active_dims (List[str]): Active dimension columns.

        Returns:
            pd.Series: Segment key identifiers.
        """
        if not active_dims:
            return pd.Series(["TOTAL"] * len(data))

        return data[active_dims].apply(lambda row: ".".join(row.astype(str)), axis=1)

    def _build_results_df(self,
                         period_data: pd.DataFrame,
                         segments: pd.DataFrame,
                         shares: Dict[str, float],
                         target_revenue: float,
                         economics_engine: Optional[object],
                         capacity_limit: Optional[float]) -> pd.DataFrame:
        """
        Build the output DataFrame for a single period's allocation.

        Calculates all metrics: SAOs, pipeline, bookings, deals, ROI, etc.

        Args:
            period_data (pd.DataFrame): Raw period data.
            segments (pd.DataFrame): Processed segments with segment_key.
            shares (dict): Allocated shares {segment_key: share}.
            target_revenue (float): Period target.
            economics_engine (optional): Economics engine.
            capacity_limit (optional): Capacity constraint.

        Returns:
            pd.DataFrame: Results with columns:
                [period_cols, dimension_cols, share, required_saos,
                 effective_asp, effective_cw_rate, projected_pipeline,
                 projected_bookings, projected_deals, capacity_flag, weighted_roi]
        """
        # Compute weighted ROI to get total SAOs
        weighted_roi = self._compute_weighted_roi(shares, segments, economics_engine, target_revenue)
        total_saos = target_revenue / weighted_roi if weighted_roi > 0 else 0

        # Check capacity constraint
        capacity_flag = 0
        if capacity_limit is not None and total_saos > capacity_limit:
            logger.warning(f"Demand ({total_saos:,.0f} SAOs) exceeds capacity ({capacity_limit:,.0f}). "
                          f"Will miss target.")
            capacity_flag = 1
            # Adjust bookings to capacity limit
            total_saos = capacity_limit

        # Build results row by row
        results_rows = []

        for seg_key, share in shares.items():
            seg_data = segments[segments["segment_key"] == seg_key].iloc[0]

            # Get base metrics
            period_num = period_data.iloc[0].get("month", 1) if "month" in period_data.columns else 1

            # Calculate volume at this share
            volume = share * total_saos

            # Get effective ROI
            base_asp = seg_data.get("asp", 0)
            base_cw = seg_data.get("close_win_rate", 0)
            is_supersized = seg_data.get("is_supersized", False)
            effective_asp, effective_cw, roi = self._get_segment_roi(
                seg_key, base_asp, base_cw, volume, economics_engine, is_supersized
            )

            # Calculate metrics
            projected_pipeline = volume * effective_asp
            projected_bookings = volume * effective_asp * effective_cw
            projected_deals = round(projected_bookings / effective_asp) if effective_asp > 0 else 0

            # Build row
            row = {
                "month": period_num,
                "segment_key": seg_key,
                "share": share,
                "required_saos": volume,
                "effective_asp": effective_asp,
                "effective_cw_rate": effective_cw,
                "projected_pipeline": projected_pipeline,
                "projected_bookings": projected_bookings,
                "projected_deals": projected_deals,
                "capacity_flag": capacity_flag,
                "weighted_roi": roi,
            }

            # Cash cycle: add in-window and deferred bookings columns
            if self.cash_cycle_enabled and economics_engine is not None:
                product = economics_engine._extract_product_from_segment(seg_key)
                iwf = economics_engine.get_in_window_factor(product, period_num)
                row["in_window_factor"] = iwf
                row["in_window_bookings"] = projected_bookings * iwf
                row["deferred_bookings"] = projected_bookings * (1.0 - iwf)
            else:
                row["in_window_factor"] = 1.0
                row["in_window_bookings"] = projected_bookings
                row["deferred_bookings"] = 0.0

            # Add dimension values from segment data
            active_dims = self._get_active_dimensions(period_data)
            for dim in active_dims:
                if dim in seg_data.index:
                    row[dim] = seg_data[dim]

            results_rows.append(row)

        results_df = pd.DataFrame(results_rows)

        # Add 'period' column if it doesn't exist (for compatibility with other modules)
        if 'period' not in results_df.columns and 'month' in results_df.columns:
            results_df['period'] = results_df['month']

        # Ensure 'projected_bookings' exists (some modules look for this column)
        if 'projected_bookings' not in results_df.columns:
            results_df['projected_bookings'] = results_df.get('projected_bookings', 0)

        # Logging summary
        total_bookings = results_df["projected_bookings"].sum()
        total_saos_allocated = results_df["required_saos"].sum()
        logger.info(f"Period allocation summary:")
        logger.info(f"  Total SAOs: {total_saos_allocated:,.0f}")
        logger.info(f"  Total Pipeline: ${results_df['projected_pipeline'].sum():,.0f}")
        logger.info(f"  Total Bookings: ${total_bookings:,.0f}")
        logger.info(f"  Target: ${target_revenue:,.0f}")
        logger.info(f"  Target achievement: {total_bookings/target_revenue:.1%}")
        if capacity_flag:
            logger.info(f"  ⚠️  CAPACITY CONSTRAINED")

        return results_df

    def get_optimization_summary(self, results: pd.DataFrame) -> Dict:
        """
        Generate a summary of the full optimization.

        Aggregates key metrics across all periods and segments.

        Args:
            results (pd.DataFrame): Output from optimize() method.

        Returns:
            dict: Summary metrics including:
                - total_annual_bookings
                - total_annual_pipeline
                - total_annual_saos
                - total_annual_deals
                - segment_shares (avg across year)
                - capacity_utilization_by_period
                - months_capacity_constrained
                - average_weighted_roi
        """
        total_bookings = results["projected_bookings"].sum()
        total_saos = results["required_saos"].sum()

        summary = {
            "total_annual_bookings": total_bookings,
            "total_annual_pipeline": results["projected_pipeline"].sum(),
            "total_annual_saos": total_saos,
            "total_annual_deals": results["projected_deals"].sum(),
            # Bookings-weighted ROI: total bookings / total SAOs.
            # This is the dollar-weighted average ROI across the plan —
            # i.e., for every SAO the business pursues, this is the
            # expected revenue return. High-volume segments (which drive
            # most bookings) contribute proportionally more than small ones.
            # Contrast with a simple mean of per-row ROI, which would treat
            # a 3%-share segment equally with a 40%-share segment.
            "average_weighted_roi": (total_bookings / total_saos) if total_saos > 0 else 0.0,
            "months_capacity_constrained": results[results["capacity_flag"] == 1]["month"].nunique(),
            "total_months": results["month"].nunique(),
        }

        # Segment-level summaries
        segment_summary = results.groupby("segment_key").agg({
            "share": "mean",
            "projected_bookings": "sum",
            "required_saos": "sum",
        }).round(2)

        # Per-segment bookings-weighted ROI (bookings / SAOs for each segment)
        segment_summary["weighted_roi"] = (
            segment_summary["projected_bookings"] / segment_summary["required_saos"]
        ).where(segment_summary["required_saos"] > 0, 0.0).round(2)

        summary["segment_summary"] = segment_summary.to_dict()

        # Cash cycle metrics (when enabled)
        if "in_window_bookings" in results.columns:
            total_in_window = results["in_window_bookings"].sum()
            total_deferred = results["deferred_bookings"].sum()
            total_bookings = summary["total_annual_bookings"]
            summary["total_in_window_bookings"] = total_in_window
            summary["total_deferred_bookings"] = total_deferred
            summary["in_window_pct"] = (
                (total_in_window / total_bookings * 100) if total_bookings > 0 else 0.0
            )

        return summary
