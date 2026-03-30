"""
VersionStore: Plan Version Persistence and Management

This module persists plan versions to disk with complete snapshots of:
- Configuration (YAML)
- Allocation results (CSV)
- Summary metrics (JSON)

Versions are stored in a versioned directory structure: versions/v001/, versions/v002/, etc.

Key Responsibilities:
- Save plan runs with auto-incrementing version IDs
- Persist config, results, and summary metrics for each version
- Load historical versions for comparison and analysis
- List all saved versions with metadata
- Compute and store summary metrics (bookings, SAOs, HC, productivity)

This enables:
- Audit trail: every plan run is permanently recorded
- What-if analysis: compare multiple scenarios side-by-side
- Re-planning: load a historical version and iterate
- Dedup detection: check if a config has been run before

Storage structure per version:
```
versions/
  v001/
    config.yaml         ← Full config used for this run
    results.csv         ← Allocation results (one row per segment per period)
    summary.json        ← Summary metrics {version_id, timestamp, description, ...}
  v002/
    config.yaml
    results.csv
    summary.json
  ...
```

Example usage:
    store = VersionStore(config)
    version_id = store.save(
        config_snapshot=config.to_dict(),
        results=allocation_df,
        summary={'total_bookings': 188000000, ...},
        description='Q2 replan after attrition spike'
    )
    loaded = store.load(version_id=1)
    all_versions = store.list_versions()
"""

import pandas as pd
import json
import yaml
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime
from .config_manager import ConfigManager
from .utils import compute_config_hash


class VersionStore:
    """
    Manages versioned storage of plan runs.

    Attributes:
        config (ConfigManager): Configuration object.
        output_dir (Path): Directory where versions are stored.
    """

    def __init__(self, config: ConfigManager) -> None:
        """
        Initialize VersionStore with configuration.

        The output directory is read from config.system.output_dir and created if needed.

        Args:
            config (ConfigManager): Configuration object.
        """
        self.config = config

        # Get output directory from config
        output_dir_str = config.get('system.output_dir', 'versions')
        self.output_dir = Path(output_dir_str)

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)


    def save(
        self,
        config_snapshot: Dict[str, Any],
        results: pd.DataFrame,
        summary: Dict[str, Any],
        description: str = "",
        planning_mode: str = "full_year"
    ) -> int:
        """
        Save a plan version to disk.

        Creates a versioned directory (v001, v002, etc.) containing:
        - config.yaml: The full configuration used for this run
        - results.csv: The allocation results dataframe
        - summary.json: Summary metrics and metadata

        Args:
            config_snapshot (dict): Full configuration dictionary for this run.
            results (pd.DataFrame): Allocation results with columns:
                                   segment, share, required_SAOs, pipeline, bookings, etc.
            summary (dict): Summary metrics dictionary. Will be augmented with:
                           version_id, timestamp, description, planning_mode, config_hash
            description (str, optional): User-provided label for this version (e.g., "Q2 replan").
                                        Defaults to empty string.
            planning_mode (str, optional): Planning mode used ('full_year', 'rolling_forward', 'manual_lock').
                                          Defaults to 'full_year'.

        Returns:
            int: The version ID (e.g., 1, 2, 3) of the saved version.

        Raises:
            ValueError: If results dataframe is invalid or config is not a dict.
            IOError: If writing to disk fails.
        """
        # Validate inputs
        if not isinstance(config_snapshot, dict):
            raise ValueError("config_snapshot must be a dictionary")
        if not isinstance(results, pd.DataFrame) or results.empty:
            raise ValueError("results must be a non-empty pandas DataFrame")

        # Get next version ID
        version_id = self._get_next_version_id()

        # Create version directory
        version_dir = self.output_dir / f"v{version_id:03d}"
        version_dir.mkdir(parents=True, exist_ok=True)

        # Compute config hash for dedup detection
        config_hash = self._compute_config_hash(config_snapshot)

        # Augment summary with metadata
        summary_with_metadata = {
            'version_id': version_id,
            'timestamp': datetime.utcnow().isoformat(),
            'description': description,
            'planning_mode': planning_mode,
            'config_hash': config_hash,
            **summary
        }

        # Save config.yaml
        config_path = version_dir / 'config.yaml'
        with open(config_path, 'w') as f:
            yaml.dump(config_snapshot, f, default_flow_style=False, sort_keys=False)

        # Save results.csv
        results_path = version_dir / 'results.csv'
        results.to_csv(results_path, index=False)

        # Save summary.json
        summary_path = version_dir / 'summary.json'
        with open(summary_path, 'w') as f:
            json.dump(summary_with_metadata, f, indent=2)

        return version_id


    def load(self, version_id: int) -> Dict[str, Any]:
        """
        Load a specific version from disk.

        Retrieves and parses all three files (config, results, summary) for the version.

        Args:
            version_id (int): Version ID to load (e.g., 1, 2, 3).

        Returns:
            dict: Dictionary with keys:
                - 'config': Loaded YAML config as dict
                - 'results': Loaded CSV as pandas DataFrame
                - 'summary': Loaded JSON as dict

        Raises:
            FileNotFoundError: If the version directory or any of its files do not exist.
            ValueError: If files cannot be parsed (invalid YAML, CSV, or JSON).
        """
        version_dir = self.output_dir / f"v{version_id:03d}"

        if not version_dir.exists():
            raise FileNotFoundError(f"Version {version_id} not found in {self.output_dir}")

        # Load config.yaml
        config_path = version_dir / 'config.yaml'
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        # Load results.csv
        results_path = version_dir / 'results.csv'
        if not results_path.exists():
            raise FileNotFoundError(f"Results file not found: {results_path}")
        results = pd.read_csv(results_path)

        # Load summary.json
        summary_path = version_dir / 'summary.json'
        if not summary_path.exists():
            raise FileNotFoundError(f"Summary file not found: {summary_path}")
        with open(summary_path, 'r') as f:
            summary = json.load(f)

        return {
            'config': config,
            'results': results,
            'summary': summary
        }


    def list_versions(self) -> pd.DataFrame:
        """
        List all saved versions with metadata.

        Scans the versions directory and reads the summary.json from each version,
        returning a dataframe with one row per version and key metadata columns.

        Returns:
            pd.DataFrame: DataFrame with columns:
                - version_id: Version ID (1, 2, 3, ...)
                - timestamp: When the version was saved
                - description: User-provided label
                - planning_mode: Planning mode used
                - config_hash: SHA256 hash of the config
                - (and any additional fields from summary metrics)

        Raises:
            IOError: If reading version directories fails.
        """
        versions = []

        # Iterate through version directories
        for version_dir in sorted(self.output_dir.glob('v*')):
            if not version_dir.is_dir():
                continue

            # Extract version ID from directory name (v001 -> 1)
            try:
                version_id = int(version_dir.name[1:])
            except (ValueError, IndexError):
                # Skip if directory name doesn't match pattern
                continue

            # Load summary.json
            summary_path = version_dir / 'summary.json'
            if not summary_path.exists():
                # Skip this version if summary is missing
                continue

            try:
                with open(summary_path, 'r') as f:
                    summary = json.load(f)
                versions.append(summary)
            except (json.JSONDecodeError, IOError):
                # Skip if summary cannot be parsed
                continue

        if not versions:
            # Return empty dataframe if no versions found
            return pd.DataFrame()

        # Convert list of dicts to dataframe
        df = pd.DataFrame(versions)

        # Sort by version_id (descending = most recent first)
        if 'version_id' in df.columns:
            df = df.sort_values('version_id', ascending=False).reset_index(drop=True)

        return df


    def _get_next_version_id(self) -> int:
        """
        Compute the next version ID by scanning existing versions.

        Auto-increment logic: find the highest existing version number and add 1.
        If no versions exist yet, return 1.

        Returns:
            int: Next version ID to use (e.g., 1, 2, 3, ...).
        """
        # Scan for existing version directories
        existing_versions = []
        for version_dir in self.output_dir.glob('v*'):
            if not version_dir.is_dir():
                continue
            try:
                # Extract version number from v001, v002, etc.
                version_num = int(version_dir.name[1:])
                existing_versions.append(version_num)
            except (ValueError, IndexError):
                # Skip if directory name doesn't match pattern
                continue

        if not existing_versions:
            return 1
        else:
            return max(existing_versions) + 1


    def _compute_config_hash(self, config_dict: Dict[str, Any]) -> str:
        """
        Compute SHA256 hash of a config dictionary for dedup detection.

        Delegates to utils.compute_config_hash — the same function used by
        ConfigManager.hash(). This guarantees that a hash produced at save time
        and a hash produced by the config manager are always comparable.

        Args:
            config_dict (dict): Configuration dictionary (plain dict, not ConfigManager).

        Returns:
            str: Hexadecimal SHA256 hash.
        """
        return compute_config_hash(config_dict)
