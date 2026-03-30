"""
Shared Utility Functions — GTM Planning Engine

This module contains functions used by multiple modules in the engine.
Centralising them here enforces a single implementation for each concern
and prevents silent divergence in business logic across modules.

Functions
---------
compute_config_hash(config_dict)
    SHA256 hash of a config dict. Used by ConfigManager and VersionStore
    for dedup detection. Single implementation ensures both modules agree
    on what constitutes a "duplicate" run.

format_currency(value)
    Convert a raw dollar value to millions (1 d.p.). Used by VersionComparator
    and WhatIfEngine for consistent display formatting in reports.
"""

import hashlib
import json
from typing import Any, Dict


def compute_config_hash(config_dict: Dict[str, Any]) -> str:
    """
    Compute a SHA256 hash of a configuration dictionary.

    Both ConfigManager and VersionStore use this to detect whether a config
    has been run before, avoiding redundant optimisation passes. Using a
    shared implementation guarantees that the two callers will always agree
    on hash identity — a split implementation risks drift that silently
    breaks dedup.

    Underscore-prefixed keys (e.g. ``_asp_multiplier``, ``_ae_headcount_changes``)
    injected by WhatIfEngine ARE included in the hash. This is intentional:
    a what-if config with different perturbations must produce a different
    hash so it is stored as a distinct version, not deduped against the base.

    Args:
        config_dict: Configuration dictionary (may be nested).

    Returns:
        str: 64-character hexadecimal SHA256 digest.
    """
    # Canonical JSON ensures key ordering does not affect the hash
    config_json = json.dumps(config_dict, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(config_json.encode('utf-8')).hexdigest()


def format_currency(value: float) -> float:
    """
    Express a raw dollar value in millions, rounded to one decimal place.

    Used by VersionComparator and WhatIfEngine when building comparison
    reports. A single implementation ensures both modules display numbers
    at the same scale and precision, so a leader comparing a comparator
    table with a what-if table sees consistent figures.

    Args:
        value: Raw dollar amount (e.g. 115_700_000).

    Returns:
        float: Value in millions (e.g. 115.7).
    """
    return round(value / 1_000_000, 1)
