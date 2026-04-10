"""
GTM Planning Engine — Monolith Flask API

Thin HTTP shell over the monolith engine. Replaces the subprocess.run()
anti-pattern in app.py with direct Python calls.

100% backward-compatible: identical API routes, response schemas, and
config.yaml ingestion.
"""

from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
from pathlib import Path
import os
import json
import sys
import re
import yaml
from datetime import datetime
import socket
import threading
import atexit
import signal
import time
from http.server import ThreadingHTTPServer

import numpy as np
import pandas as pd

from gtm_monolith.engine import (
    GTMConfig,
    DataLayer,
    TargetLayer,
    CapacityLayer,
    EconomicsLayer,
    OptimizerLayer,
    ValidationLayer,
    RecoveryLayer,
    VersionStoreLayer,
    AdjustmentLayer,
    WhatIfLayer,
    ComparatorLayer,
    LeverAnalysisLayer,
)
from gtm_monolith.run_plan_monolith import (
    build_enriched_summary,
    sanitize_summary,
    build_monthly_waterfall,
    build_economics_decay,
    build_cashcycle_waterfall,
    prepare_recovery_inputs,
    json_safe,
)

app = Flask(__name__)
CORS(app, origins=[r"https://.*\.lovable\.app", r"https://.*\.lovableproject\.com"])

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"
VERSIONS_DIR = PROJECT_ROOT / "versions"
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

# Chart server management
CHART_SERVERS = {}
CHART_SERVER_START_PORT = 8765
CHART_SERVER_LOCK = threading.Lock()

# Import chart server components
sys.path.insert(0, str(PROJECT_ROOT / "reportingCharts"))
try:
    from run_charts import build_handler
    CHARTS_AVAILABLE = True
except ImportError:
    CHARTS_AVAILABLE = False


def find_available_port(start_port=CHART_SERVER_START_PORT):
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError("No available ports found for chart server")


def start_chart_server_thread(version_id):
    if not CHARTS_AVAILABLE:
        raise RuntimeError("Chart server module not available")
    version_dir = VERSIONS_DIR / version_id
    if not version_dir.exists():
        raise ValueError(f"Version directory not found: {version_dir}")

    port = find_available_port()
    host = '127.0.0.1'

    handler_class = build_handler(version_dir)
    server = ThreadingHTTPServer((host, port), handler_class)

    def run_server():
        try:
            server.serve_forever()
        except Exception as e:
            print(f"Chart server for {version_id} error: {e}")
        finally:
            with CHART_SERVER_LOCK:
                if version_id in CHART_SERVERS:
                    del CHART_SERVERS[version_id]

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    with CHART_SERVER_LOCK:
        CHART_SERVERS[version_id] = {
            'server': server,
            'thread': server_thread,
            'port': port,
            'host': host,
            'url': f'http://{host}:{port}/',
            'version_id': version_id
        }

    return port


def stop_chart_server(version_id):
    with CHART_SERVER_LOCK:
        if version_id not in CHART_SERVERS:
            return False
        server_info = CHART_SERVERS[version_id]

    try:
        server_info['server'].shutdown()
        server_info['thread'].join(timeout=5)
    except Exception as e:
        print(f"Error stopping chart server for {version_id}: {e}")
    finally:
        with CHART_SERVER_LOCK:
            if version_id in CHART_SERVERS:
                del CHART_SERVERS[version_id]
        return True


def cleanup_all_chart_servers():
    print("Cleaning up all chart servers...")
    with CHART_SERVER_LOCK:
        version_ids = list(CHART_SERVERS.keys())
    for version_id in version_ids:
        stop_chart_server(version_id)
    print("Chart server cleanup complete")


def kill_process_on_port(port):
    current_pid = os.getpid()
    try:
        import subprocess
        result = subprocess.run(
            ["lsof", "-t", f"-i:{port}"],
            capture_output=True, text=True, check=False
        )
        pids = [
            int(pid.strip())
            for pid in result.stdout.splitlines()
            if pid.strip().isdigit() and int(pid.strip()) != current_pid
        ]
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                continue
        if pids:
            time.sleep(0.3)
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    continue
    except Exception:
        pass


def read_bool_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_version_id(version_id):
    if not version_id:
        return version_id
    normalized = str(version_id).strip()
    if normalized.startswith('v'):
        return normalized
    if normalized.isdigit():
        return f"v{int(normalized):03d}"
    return normalized


def parse_timestamp_to_epoch(value):
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return int(float(stripped))
        except ValueError:
            try:
                return int(datetime.fromisoformat(stripped.replace('Z', '+00:00')).timestamp())
            except ValueError:
                return int(datetime.now().timestamp())
    return int(datetime.now().timestamp())


def deep_merge_dict(base, updates):
    if not isinstance(base, dict) or not isinstance(updates, dict):
        return updates
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_cash_cycle_distribution_keys(config):
    economics = config.get("economics")
    if not isinstance(economics, dict):
        return
    cash_cycle = economics.get("cash_cycle")
    if not isinstance(cash_cycle, dict):
        return

    def normalize_distribution(distribution):
        if not isinstance(distribution, dict):
            return distribution
        normalized = {}
        for key, value in distribution.items():
            normalized_key = key
            if isinstance(key, str) and key.isdigit():
                normalized_key = int(key)
            normalized[normalized_key] = value
        return normalized

    cash_cycle["default_distribution"] = normalize_distribution(cash_cycle.get("default_distribution"))
    product_overrides = cash_cycle.get("product_overrides")
    if isinstance(product_overrides, dict):
        cash_cycle["product_overrides"] = {
            product: normalize_distribution(distribution)
            for product, distribution in product_overrides.items()
        }


atexit.register(cleanup_all_chart_servers)


# ── Static routes ──────────────────────────────────────────────────


@app.route('/')
def index():
    return send_from_directory(str(PROJECT_ROOT / 'frontend'), 'index.html')


@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(str(PROJECT_ROOT / 'frontend'), filename)


@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "gtm-planning-engine"})


# ── Config routes ──────────────────────────────────────────────────


@app.route('/api/config-schema', methods=['GET'])
def get_config_schema():
    try:
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": f"Failed to load config schema: {str(e)}"}), 500


@app.route('/api/config/defaults', methods=['GET'])
def get_config_defaults():
    try:
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": f"Failed to load config defaults: {str(e)}"}), 500


# ── Version routes ─────────────────────────────────────────────────


@app.route('/api/versions', methods=['GET'])
def list_versions():
    versions = []
    if VERSIONS_DIR.exists():
        for version_path in sorted(VERSIONS_DIR.glob('v*')):
            version_id = version_path.name
            summary_file = version_path / 'summary.json'
            if summary_file.exists():
                try:
                    with open(summary_file) as f:
                        summary = json.load(f)
                    versions.append({
                        'id': version_id,
                        'description': summary.get('description', 'No description'),
                        'created': parse_timestamp_to_epoch(summary.get('timestamp'))
                    })
                except Exception:
                    pass
    return jsonify({"versions": versions})


@app.route('/api/version/<version_id>/summary', methods=['GET'])
def get_version_summary(version_id):
    version_id = normalize_version_id(version_id)
    summary_file = VERSIONS_DIR / version_id / 'summary.json'
    if not summary_file.exists():
        return jsonify({"error": "Version not found"}), 404
    with open(summary_file) as f:
        summary = json.load(f)
    return jsonify(summary)


@app.route('/api/version/<version_id>/results', methods=['GET'])
def get_version_results(version_id):
    version_id = normalize_version_id(version_id)
    results_file = VERSIONS_DIR / version_id / 'results.csv'
    if not results_file.exists():
        return jsonify({"error": "Results not found"}), 404
    df = pd.read_csv(results_file)
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/version/<version_id>/files', methods=['GET'])
def list_version_files(version_id):
    version_id = normalize_version_id(version_id)
    version_dir = VERSIONS_DIR / version_id
    if not version_dir.exists():
        return jsonify({"error": "Version not found"}), 404
    files = [f.name for f in version_dir.iterdir() if f.is_file()]
    return jsonify({"version_id": version_id, "files": sorted(files)})


@app.route('/api/version/<version_id>/recommendations', methods=['GET'])
def get_version_recommendations(version_id):
    version_id = normalize_version_id(version_id)
    recs_file = VERSIONS_DIR / version_id / 'lever_analysis.txt'
    if not recs_file.exists():
        recs_file = VERSIONS_DIR / version_id / 'recommendations.txt'
    if not recs_file.exists():
        return jsonify({"error": "No recommendations found"}), 404
    return recs_file.read_text(), 200, {'Content-Type': 'text/plain'}


@app.route('/api/version/<version_id>/download/<filename>')
def download_version_file(version_id, filename):
    version_id = normalize_version_id(version_id)
    version_dir = VERSIONS_DIR / version_id
    if not version_dir.exists():
        return jsonify({"error": "Version not found"}), 404
    file_path = version_dir / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_from_directory(version_dir, filename)


# ── Run plan (direct call, no subprocess) ──────────────────────────


def _run_full_pipeline(runtime_config: dict, description: str) -> dict:
    """Execute the full 8-stage pipeline and return version info.

    This replaces the subprocess.run() call to run_plan.py with direct
    in-process execution using the monolith engine classes.

    The config dict goes through a YAML round-trip to normalize types
    (matching the old subprocess approach where config was written to a
    temp YAML file and then re-read by run_plan.py).
    """
    import time as _time

    # YAML round-trip: normalize JSON string keys → YAML native types
    # (e.g., seasonality_weights: {"1": 0.07} → {1: 0.07})
    # This matches the old subprocess approach exactly.
    normalized_config = yaml.safe_load(yaml.safe_dump(runtime_config, sort_keys=False))
    config = GTMConfig.from_dict(normalized_config)
    data_path = str(DATA_DIR / "2025_actuals.csv")
    t0 = _time.monotonic()

    def _elapsed():
        return f"{_time.monotonic() - t0:.1f}s"

    # Stage 2: Data
    print(f"[pipeline] Stage 2: Loading data...", flush=True)
    loader = DataLayer(config)
    df_raw = loader.load(data_path)
    df_clean = loader.prepare(df_raw)
    baselines = loader.compute_segment_baselines(df_clean)
    print(f"[pipeline] Stage 2 done ({_elapsed()})", flush=True)

    # Stage 3: Targets
    print(f"[pipeline] Stage 3: Generating targets...", flush=True)
    target_gen = TargetLayer(config)
    targets = target_gen.generate()
    print(f"[pipeline] Stage 3 done ({_elapsed()})", flush=True)

    # Stage 4: Capacity
    print(f"[pipeline] Stage 4: Calculating capacity...", flush=True)
    ae_model = CapacityLayer(config)
    capacity = ae_model.calculate()
    print(f"[pipeline] Stage 4 done ({_elapsed()})", flush=True)

    # Stage 5: Economics
    print(f"[pipeline] Stage 5: Economics engine...", flush=True)
    economics = EconomicsLayer(config)
    economics.load_baselines(baselines)
    print(f"[pipeline] Stage 5 done ({_elapsed()})", flush=True)

    # Stage 6: Optimization
    print(f"[pipeline] Stage 6: Running allocation optimizer...", flush=True)

    def _optimizer_timeout_handler(signum, frame):
        raise TimeoutError("Optimizer exceeded 120 second timeout")

    signal.signal(signal.SIGALRM, _optimizer_timeout_handler)
    signal.alarm(120)
    try:
        optimizer = OptimizerLayer(config)
        results = optimizer.optimize(
            targets=targets,
            base_data=df_clean,
            economics_engine=economics,
            capacity=capacity,
        )
        signal.alarm(0)  # Cancel alarm on success
        opt_summary = optimizer.get_optimization_summary(results)
        enriched = build_enriched_summary(opt_summary, capacity, results)
        print(f"[pipeline] Stage 6 done ({_elapsed()})", flush=True)
    except TimeoutError:
        signal.alarm(0)
        print(f"[pipeline] Stage 6 TIMEOUT after 120 seconds — optimizer hung", flush=True)
        raise RuntimeError(
            "Optimizer timeout: scipy.optimize.minimize() exceeded 120 seconds. "
            "This is a known scipy bug with certain constraint configurations. "
            "Try adjusting allocation.constraints (share_floor/share_ceiling) or "
            "set allocation.optimizer_mode to 'greedy'."
        )
    except Exception as e:
        signal.alarm(0)
        print(f"[pipeline] Stage 6 ERROR: {e}", flush=True)
        raise

    # Stage 7: Validation
    print(f"[pipeline] Stage 7: Validating...", flush=True)
    validator = ValidationLayer(config)
    validation = validator.validate(results, targets=targets, capacity=capacity)
    overall_pass = validation.get("passed", False) if isinstance(validation, dict) else False
    print(f"[pipeline] Stage 7 done ({_elapsed()})", flush=True)

    # Stage 8: Recovery
    print(f"[pipeline] Stage 8: Recovery analysis...", flush=True)
    recovery_engine = RecoveryLayer(config)
    targets_r, capacity_r = prepare_recovery_inputs(targets, capacity)
    recovery_analysis = recovery_engine.analyze(results, targets_r, capacity_r)
    print(f"[pipeline] Stage 8 done ({_elapsed()})", flush=True)

    # Save version
    print(f"[pipeline] Saving version...", flush=True)
    summary_dict = sanitize_summary(enriched)
    store = VersionStoreLayer(config)
    version_id = store.save(
        config_snapshot=config.to_dict(),
        results=results,
        summary=summary_dict,
        description=description,
        planning_mode=config.get("targets.planning_mode", "full_year"),
    )

    version_dir = Path(config.get("system.output_dir", "versions")) / f"v{version_id:03d}"

    # Write intermediate files
    targets.to_csv(version_dir / "targets.csv", index=False)
    capacity.to_csv(version_dir / "ae_capacity.csv", index=False)

    baselines_df = pd.DataFrame([
        {"segment": seg, "asp": vals["asp"], "win_rate": vals["win_rate"]}
        for seg, vals in baselines.items()
    ])
    baselines_df.to_csv(version_dir / "economics_baselines.csv", index=False)

    decay_df = build_economics_decay(baselines, economics)
    decay_df.to_csv(version_dir / "economics_decay.csv", index=False)

    with open(version_dir / "validation_report.json", "w") as f:
        json.dump(validation, f, indent=2, default=json_safe)

    with open(version_dir / "recovery_analysis.json", "w") as f:
        json.dump(recovery_analysis, f, indent=2, default=json_safe)

    waterfall = build_monthly_waterfall(targets, capacity, results)
    waterfall.to_csv(version_dir / "monthly_waterfall.csv", index=False)

    try:
        lever_engine = LeverAnalysisLayer(config.to_dict())
        lever_report = lever_engine.analyze(results, capacity, targets, baselines)
        lever_df = lever_engine.to_dataframe(lever_report)
        lever_df.to_csv(version_dir / "lever_analysis.csv", index=False)
        with open(version_dir / "lever_recommendations.txt", "w") as f:
            f.write(lever_report["recommendations_text"])
        report_json = {
            "gap": lever_report["gap"],
            "gap_pct": round(lever_report["gap"] / lever_report["annual_target"] * 100, 2) if lever_report["annual_target"] else 0,
            "annual_target": lever_report["annual_target"],
            "actual_bookings": lever_report["actual_bookings"],
            "sao_shadow_price": lever_report["sao_shadow_price"],
        }
        with open(version_dir / "lever_analysis_report.json", "w") as f:
            json.dump(report_json, f, indent=2, default=json_safe)
    except Exception as e:
        print(f"Lever analysis skipped: {e}")

    cash_cycle_cfg = config.get("economics.cash_cycle", {})
    cash_cycle_enabled = isinstance(cash_cycle_cfg, dict) and cash_cycle_cfg.get("enabled", False)
    if cash_cycle_enabled:
        waterfall_cc = build_cashcycle_waterfall(results, economics, config)
        waterfall_cc.to_csv(version_dir / "cashcycle_waterfall.csv", index=False)

    print(f"[pipeline] COMPLETE in {_elapsed()} — version v{version_id:03d}", flush=True)
    return {
        "version_id": f"v{version_id:03d}",
        "summary": summary_dict,
        "validation_passed": overall_pass,
    }


@app.route('/api/run-plan', methods=['POST'])
def run_plan():
    try:
        data = request.json or {}

        description = data.get('description', 'API Run')
        mode = data.get('mode', 'full')
        auto_start_charts = data.get('auto_start_charts', True)

        with open(CONFIG_FILE) as f:
            base_config = yaml.safe_load(f) or {}

        runtime_config = dict(data)
        runtime_config.pop('description', None)
        runtime_config.pop('mode', None)
        runtime_config.pop('auto_start_charts', None)

        if not runtime_config or all(k in ['description', 'mode', 'auto_start_charts'] for k in data.keys()):
            runtime_config = base_config
        else:
            runtime_config = deep_merge_dict(base_config, runtime_config)

        normalize_cash_cycle_distribution_keys(runtime_config)

        # Set 180-second hard timeout for the entire pipeline
        def _pipeline_timeout_handler(signum, frame):
            raise TimeoutError("Pipeline exceeded 180 second timeout")

        signal.signal(signal.SIGALRM, _pipeline_timeout_handler)
        signal.alarm(180)
        try:
            result = _run_full_pipeline(runtime_config, description)
            signal.alarm(0)  # Cancel alarm on success
        except TimeoutError:
            signal.alarm(0)
            return jsonify({
                "error": "Pipeline timeout: optimizer hung for >120 seconds. This is a known scipy bug.",
                "suggestion": (
                    "Try adjusting allocation.constraints.share_floor/share_ceiling "
                    "or set allocation.optimizer_mode to 'greedy'."
                ),
            }), 504
        except Exception as e:
            signal.alarm(0)
            return jsonify({"error": str(e)}), 500

        version_id = result["version_id"]
        response = {
            "version_id": version_id,
            "summary": result["summary"],
            "validation_passed": result["validation_passed"],
            "stdout": f"Version {version_id} saved to versions/{version_id}/\nPIPELINE COMPLETE",
        }

        if auto_start_charts and CHARTS_AVAILABLE:
            try:
                chart_port = start_chart_server_thread(version_id)
                with CHART_SERVER_LOCK:
                    if version_id in CHART_SERVERS:
                        response["charts"] = {
                            "port": chart_port,
                            "url": CHART_SERVERS[version_id]['url'],
                            "status": "started"
                        }
                    else:
                        response["charts"] = {
                            "status": "failed",
                            "error": "Chart server did not start properly"
                        }
            except Exception as e:
                response["charts"] = {
                    "status": "failed",
                    "error": str(e)
                }

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Chart server routes ────────────────────────────────────────────


@app.route('/api/charts/server/<version_id>', methods=['POST'])
def start_chart_server_route(version_id):
    try:
        version_id = normalize_version_id(version_id)
        version_dir = VERSIONS_DIR / version_id
        if not version_dir.exists():
            return jsonify({"error": f"Version {version_id} not found"}), 404

        with CHART_SERVER_LOCK:
            if version_id in CHART_SERVERS:
                server_info = CHART_SERVERS[version_id]
                return jsonify({
                    "status": "already_running",
                    "port": server_info['port'],
                    "url": server_info['url']
                })

        port = start_chart_server_thread(version_id)

        with CHART_SERVER_LOCK:
            if version_id in CHART_SERVERS:
                server_info = CHART_SERVERS[version_id]
                return jsonify({
                    "status": "started",
                    "port": server_info['port'],
                    "url": server_info['url'],
                    "version_id": version_id
                })
            else:
                return jsonify({
                    "status": "failed",
                    "error": "Chart server did not start properly"
                }), 500

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to start chart server: {str(e)}"}), 500


@app.route('/api/charts/server/<version_id>', methods=['DELETE'])
def stop_chart_server_route(version_id):
    try:
        version_id = normalize_version_id(version_id)
        success = stop_chart_server(version_id)
        if success:
            return jsonify({"status": "stopped", "version_id": version_id})
        else:
            return jsonify({"status": "not_running", "version_id": version_id}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to stop chart server: {str(e)}"}), 500


@app.route('/api/charts/server/<version_id>/status')
def chart_server_status(version_id):
    try:
        version_id = normalize_version_id(version_id)
        with CHART_SERVER_LOCK:
            if version_id in CHART_SERVERS:
                server_info = CHART_SERVERS[version_id]
                is_alive = server_info['thread'].is_alive()
                if is_alive:
                    return jsonify({
                        "status": "running",
                        "version_id": version_id,
                        "port": server_info['port'],
                        "url": server_info['url']
                    })
                else:
                    del CHART_SERVERS[version_id]
                    return jsonify({"status": "stopped", "version_id": version_id})
            else:
                return jsonify({"status": "not_found", "version_id": version_id}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to check chart server status: {str(e)}"}), 500


@app.route('/api/charts/servers', methods=['GET'])
def list_chart_servers():
    try:
        with CHART_SERVER_LOCK:
            servers = []
            dead_servers = []
            for version_id, server_info in list(CHART_SERVERS.items()):
                is_alive = server_info['thread'].is_alive()
                if is_alive:
                    servers.append({
                        "version_id": version_id,
                        "port": server_info['port'],
                        "url": server_info['url']
                    })
                else:
                    dead_servers.append(version_id)
            for version_id in dead_servers:
                del CHART_SERVERS[version_id]
            return jsonify({"servers": servers, "count": len(servers)})
    except Exception as e:
        return jsonify({"error": f"Failed to list chart servers: {str(e)}"}), 500


# ── Viewer route ───────────────────────────────────────────────────


@app.route('/viewer/<version_id>')
def viewer(version_id):
    version_id = normalize_version_id(version_id)
    version_dir = VERSIONS_DIR / version_id
    if not version_dir.exists():
        return f"Version {version_id} not found", 404

    return render_template_string('''
<!DOCTYPE html>
<html>
<head>
    <title>GTM Planning Engine - Viewer</title>
    <style>
        body { margin: 0; padding: 20px; font-family: Arial, sans-serif; }
        .nav { margin-bottom: 20px; padding: 10px; background: #f0f0f0; }
        .nav a { margin-right: 15px; text-decoration: none; color: #007bff; }
        iframe { width: 100%; height: 800px; border: 1px solid #ddd; }
    </style>
</head>
<body>
    <div class="nav">
        <a href="/">&#8592; Back to Main</a>
        <a href="/api/version/{{ version_id }}/summary">Summary</a>
        <a href="/api/version/{{ version_id }}/download/results.csv">Download Results</a>
        <a href="/api/charts/server/{{ version_id }}" target="_blank">Start Chart Server</a>
    </div>
    <div id="chart-server-container">
        <p>Chart server status: <span id="chart-status">Checking...</span></p>
    </div>
    <script>
        fetch('/api/charts/server/{{ version_id }}/status')
            .then(r => r.json())
            .then(data => {
                const statusEl = document.getElementById('chart-status');
                if (data.status === 'running') {
                    statusEl.innerHTML = `<a href="${data.url}" target="_blank">View Charts (Port ${data.port})</a>`;
                    const iframe = document.createElement('iframe');
                    iframe.src = data.url;
                    iframe.style.width = '100%';
                    iframe.style.height = '800px';
                    iframe.style.border = '1px solid #ddd';
                    document.getElementById('chart-server-container').appendChild(iframe);
                } else {
                    statusEl.textContent = 'Not running - Click "Start Chart Server" to start';
                }
            })
            .catch(err => {
                document.getElementById('chart-status').textContent = 'Error checking status';
            });
    </script>
</body>
</html>
''', version_id=version_id)


if __name__ == '__main__':
    try:
        port = int(os.environ.get('PORT', 8000))
    except (TypeError, ValueError):
        port = 8000
    host = os.environ.get('HOST', '0.0.0.0')
    debug_mode = read_bool_env('APP_DEBUG', False)
    use_reloader = read_bool_env('APP_RELOADER', False)
    dev_port_cleanup = read_bool_env('DEV_PORT_CLEANUP', True)
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    should_cleanup_port = port == 8000 and dev_port_cleanup and (not use_reloader or not is_reloader_child)
    if should_cleanup_port:
        kill_process_on_port(port)
    app.run(host=host, port=port, debug=debug_mode, use_reloader=use_reloader)
