"""
GTM Planning Engine

A comprehensive Python package for building, simulating, and optimising
Go-To-Market (GTM) plans. Integrates configuration management, data loading,
target generation, economic modelling, capacity planning, and optimisation
engines to enable data-driven GTM strategy development and scenario analysis.

The package supports multi-dimensional planning including:
- Territory and account targeting
- Sales force capacity optimisation
- Revenue forecasting and economics modelling
- Scenario analysis and what-if modelling
- Version control and comparison of plans
- Validation and adjustment workflows

Module map
----------
ConfigManager       config_manager.py   — Load / validate YAML, dot-notation access
DataLoader          data_loader.py      — Ingest, clean, confidence-score actuals
TargetGenerator     target_generator.py — Distribute annual target across periods
AECapacityModel     ae_capacity.py      — AE workforce capacity by month
EconomicsEngine     economics_engine.py — Marginal ASP / CW decay curves
CalibrationEngine   economics_engine.py — Fit decay curves from deal-level data
AllocationOptimizer optimizer.py        — Greedy + SLSQP allocation across segments
AdjustmentEngine    adjustments.py      — Mid-cycle re-planning (lock actuals, re-target)
ValidationEngine    validation.py       — Mathematical consistency checks
RecoveryEngine      recovery.py         — Quarterly shortfall redistribution
VersionComparator   comparator.py       — Multi-dimensional plan version comparison
VersionStore        version_store.py    — Versioned persistence (config + results + summary)
WhatIfEngine        what_if.py          — Named scenario analysis against base plan
"""

__version__ = "0.1.0"

# Foundation layer
from .config_manager import ConfigManager
from .data_loader import DataLoader
from .version_store import VersionStore

# Planning pipeline
from .target_generator import TargetGenerator
from .ae_capacity import AECapacityModel
from .economics_engine import EconomicsEngine, CalibrationEngine
from .optimizer import AllocationOptimizer

# Post-optimisation modules
from .adjustments import AdjustmentEngine
from .validation import ValidationEngine
from .recovery import RecoveryEngine

# Analysis and persistence
from .comparator import VersionComparator
from .what_if import WhatIfEngine
from .lever_analysis import LeverAnalysisEngine

__all__ = [
    # Foundation
    "ConfigManager",
    "DataLoader",
    "VersionStore",
    # Planning pipeline
    "TargetGenerator",
    "AECapacityModel",
    "EconomicsEngine",
    "CalibrationEngine",
    "AllocationOptimizer",
    # Post-optimisation
    "AdjustmentEngine",
    "ValidationEngine",
    "RecoveryEngine",
    # Analysis and persistence
    "VersionComparator",
    "WhatIfEngine",
    "LeverAnalysisEngine",
]
