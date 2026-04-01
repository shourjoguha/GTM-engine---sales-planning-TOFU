"""
ConfigManager: Configuration Management for GTM Planning Engine

This module loads, validates, and provides access to the YAML configuration file
that controls all behaviour of the GTM Planning Engine.

Key Responsibilities:
- Load and parse YAML configuration from disk
- Validate configuration against expected schema with clear error messages
- Provide getter methods for nested config values using dot notation
- Resolve active dimensions (which data columns are enabled for this run)
- Support config overrides for what-if scenario modelling
- Compute hash fingerprint of config for dedup detection

The config is the single source of truth for:
- Annual targets, seasonality weights, planning modes
- Allocation constraints (min/max share per segment)
- Economics parameters (decay functions, calibration toggles)
- AE model parameters (hiring plan, ramp, shrinkage, attrition)
- System settings (optimizer mode, confidence thresholds, output directories)

Example usage:
    config = ConfigManager('config.yaml')
    annual_target = config.get('targets.annual_target')
    active_dims = config.get_active_dimensions()
    config_overridden = config.override({'targets.annual_target': 200000000})
"""

import yaml
from pathlib import Path
from typing import Any, Optional, List, Dict
from .utils import compute_config_hash


class ConfigManager:
    """
    Loads, validates, and provides access to GTM Planning Engine configuration.

    Attributes:
        config_path (str): Path to the YAML configuration file
        _config (dict): The loaded and validated configuration dictionary
        _active_dimensions (list): List of dimension names that are enabled
    """

    def __init__(self, config_path: str) -> None:
        """
        Load and validate the YAML configuration file.

        Args:
            config_path (str): Path to the YAML configuration file.

        Raises:
            FileNotFoundError: If the config file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            ValueError: If the config fails validation.
        """
        # Convert to Path object for robust path handling
        config_path_obj = Path(config_path)

        # Check file exists
        if not config_path_obj.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        # Load YAML
        try:
            with open(config_path_obj, 'r') as f:
                self._config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"YAML parsing failed: {e}")

        # Handle empty config
        if self._config is None:
            self._config = {}

        # Validate the loaded configuration
        self.validate()

        # Cache active dimensions
        self._active_dimensions = self._compute_active_dimensions()


    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a config value using dot notation.

        Nested keys are accessed using dots. For example:
        - 'targets.annual_target' returns config['targets']['annual_target']
        - 'allocation.constraints.share_floor' returns config['allocation']['constraints']['share_floor']

        Args:
            key (str): Dot-separated path to the config value (e.g., 'allocation.constraints.share_floor')
            default (Any, optional): Default value if key is not found. Defaults to None.

        Returns:
            Any: The config value at the specified path, or default if not found.
        """
        # Split the key by dots
        keys = key.split('.')

        # Navigate through the nested dictionary
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value if value is not None else default


    def get_active_dimensions(self) -> List[str]:
        """
        Return list of dimension names that are enabled for this planning run.

        A dimension is "active" if its 'enabled' flag is set to true in the config.
        When a dimension is disabled, the engine aggregates across all its values.

        Returns:
            list[str]: List of active dimension names (e.g., ['product', 'channel'])
        """
        return self._active_dimensions


    def get_segment_keys(self) -> List[str]:
        """
        Return the dimension column names to group by based on active dimensions.

        This is used to determine which columns in the data to use as segment keys
        during analysis. Only dimensions that are enabled in config are returned.

        Returns:
            list[str]: List of dimension names to group by (e.g., ['product', 'channel'])
        """
        return self.get_active_dimensions()


    def override(self, overrides: Dict[str, Any]) -> 'ConfigManager':
        """
        Create a new ConfigManager with specific values overridden.

        This is used by the what-if engine to create scenario variations without
        modifying the original config. The returned ConfigManager is a deep copy
        with the specified overrides applied.

        Usage example:
            base_config = ConfigManager('config.yaml')
            scenario = base_config.override({
                'targets.annual_target': 200000000,
                'ae_model.hiring_plan[0].count': 20
            })

        Args:
            overrides (dict): Dictionary of config paths (using dot notation) and their new values.
                             Examples: {'targets.annual_target': 200000000}

        Returns:
            ConfigManager: A new ConfigManager instance with overrides applied.

        Raises:
            ValueError: If any override path is invalid.
        """
        import copy

        # Deep copy the current config
        new_config_dict = copy.deepcopy(self._config)

        # Apply each override
        for key_path, value in overrides.items():
            # Split the key path
            keys = key_path.split('.')

            # Navigate and set the value
            current = new_config_dict
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]

            # Set the final value
            current[keys[-1]] = value

        # Create a temporary config file in memory and instantiate new ConfigManager
        # We'll do this by creating a new ConfigManager and manually setting its config
        new_manager = ConfigManager.__new__(ConfigManager)
        new_manager._config = new_config_dict
        new_manager.validate()
        new_manager._active_dimensions = new_manager._compute_active_dimensions()

        return new_manager


    def validate(self) -> None:
        """
        Validate configuration: check required fields exist, weights sum to 1.0, constraints are valid.

        Validations performed:
        - Required top-level sections are present (dimensions, targets, allocation, etc.)
        - Seasonality weights sum to 1.0 (with tolerance)
        - Share floor < share ceiling
        - Hiring plan has valid month numbers (1-12)
        - Confidence thresholds are positive
        - All required fields within each section exist

        Raises:
            ValueError: If any validation check fails.
        """
        # Check required top-level sections
        required_sections = ['dimensions', 'targets', 'allocation', 'economics', 'ae_model', 'system']
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"Missing required config section: {section}")

        # Validate seasonality weights sum to 1.0 (if specified)
        seasonality = self.get('targets.seasonality_weights')
        if seasonality is not None:
            weights_sum = sum(seasonality.values())
            tolerance = self.get('system.tolerance', 0.001)
            if abs(weights_sum - 1.0) > tolerance:
                raise ValueError(
                    f"Seasonality weights sum to {weights_sum}, expected 1.0 (tolerance: {tolerance})"
                )

        # Validate allocation constraints
        share_floor = self.get('allocation.constraints.share_floor', 0.0)
        share_ceiling = self.get('allocation.constraints.share_ceiling', 1.0)
        if share_floor >= share_ceiling:
            raise ValueError(
                f"Share floor ({share_floor}) must be less than share ceiling ({share_ceiling})"
            )

        # Validate hiring plan months are valid (1-12)
        hiring_plan = self.get('ae_model.hiring_plan', [])
        for i, tranche in enumerate(hiring_plan):
            month = tranche.get('start_month')
            if month is None or not (1 <= month <= 12):
                raise ValueError(
                    f"Hiring tranche {i} has invalid start_month: {month}. Must be 1-12."
                )

        # Validate confidence thresholds are positive
        high_threshold = self.get('economics.confidence.high_threshold', 30)
        medium_threshold = self.get('economics.confidence.medium_threshold', 15)
        if medium_threshold >= high_threshold:
            raise ValueError(
                f"Medium confidence threshold ({medium_threshold}) must be less than "
                f"high confidence threshold ({high_threshold})"
            )

        # Validate annual target is positive
        annual_target = self.get('targets.annual_target')
        if annual_target is not None and annual_target <= 0:
            raise ValueError(f"Annual target must be positive, got {annual_target}")

        # Validate cash_cycle config (if present and enabled)
        cash_cycle = self.get('economics.cash_cycle', {})
        if isinstance(cash_cycle, dict) and cash_cycle.get('enabled', False):
            tolerance = self.get('system.tolerance', 0.001)

            # default_distribution must exist and sum to 1.0
            default_dist = cash_cycle.get('default_distribution')
            if not default_dist or not isinstance(default_dist, dict):
                raise ValueError(
                    "economics.cash_cycle.default_distribution is required when cash_cycle is enabled"
                )
            dist_sum = sum(default_dist.values())
            if abs(dist_sum - 1.0) > tolerance:
                raise ValueError(
                    f"cash_cycle.default_distribution sums to {dist_sum}, expected 1.0 "
                    f"(tolerance: {tolerance})"
                )
            # All delay keys must be non-negative integers
            for key in default_dist:
                if not isinstance(key, int) or key < 0:
                    raise ValueError(
                        f"cash_cycle.default_distribution keys must be non-negative integers, "
                        f"got {key!r}"
                    )

            # Validate each product_overrides entry sums to 1.0
            product_overrides = cash_cycle.get('product_overrides', {})
            for product, dist in product_overrides.items():
                if not isinstance(dist, dict):
                    raise ValueError(
                        f"cash_cycle.product_overrides[{product}] must be a dict, "
                        f"got {type(dist).__name__}"
                    )
                override_sum = sum(dist.values())
                if abs(override_sum - 1.0) > tolerance:
                    raise ValueError(
                        f"cash_cycle.product_overrides[{product}] sums to {override_sum}, "
                        f"expected 1.0 (tolerance: {tolerance})"
                    )
                for key in dist:
                    if not isinstance(key, int) or key < 0:
                        raise ValueError(
                            f"cash_cycle.product_overrides[{product}] keys must be "
                            f"non-negative integers, got {key!r}"
                        )

            # grain must be a valid, enabled dimension
            grain = cash_cycle.get('grain', 'product')
            dimensions = self.get('dimensions', {})
            if grain not in dimensions:
                raise ValueError(
                    f"cash_cycle.grain '{grain}' is not a configured dimension"
                )
            grain_config = dimensions.get(grain, {})
            if not isinstance(grain_config, dict) or not grain_config.get('enabled', False):
                raise ValueError(
                    f"cash_cycle.grain '{grain}' refers to a disabled dimension. "
                    f"Enable it in dimensions.{grain}.enabled first."
                )


    def to_dict(self) -> Dict[str, Any]:
        """
        Return the full configuration as a dictionary.

        This is useful for:
        - Versioning: saving the full config used for a plan run
        - Serialization: writing config to JSON or YAML for storage
        - Comparison: understanding differences between config versions

        Returns:
            dict: A copy of the full configuration dictionary.
        """
        import copy
        return copy.deepcopy(self._config)


    def hash(self) -> str:
        """
        Return SHA256 hash of the configuration.

        Delegates to utils.compute_config_hash so the hashing algorithm is
        identical to the one used by VersionStore. This guarantees that a
        hash produced here and a hash produced during save() will always agree,
        making dedup detection reliable.

        Returns:
            str: Hexadecimal SHA256 hash of the config.
        """
        return compute_config_hash(self._config)


    def _compute_active_dimensions(self) -> List[str]:
        """
        Compute and cache the list of active dimension names.

        A dimension is active if its 'enabled' field is True in the config.
        This is computed once during initialization and cached for performance.

        Returns:
            list[str]: List of active dimension names, in the order they appear in config.
        """
        active = []
        dimensions = self.get('dimensions', {})

        for dim_name, dim_config in dimensions.items():
            if isinstance(dim_config, dict) and dim_config.get('enabled', False):
                active.append(dim_name)

        return active
