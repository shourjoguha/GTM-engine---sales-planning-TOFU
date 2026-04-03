from flask import Flask, request, jsonify, send_from_directory, render_template_string
from pathlib import Path
import os
import json
import sys
import subprocess
import tempfile
import shutil
import re
import yaml
from datetime import datetime
import socket
import threading
import atexit
import signal
import time
from http.server import ThreadingHTTPServer

app = Flask(__name__)

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"
VERSIONS_DIR = PROJECT_ROOT / "versions"
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

# Chart server management
CHART_SERVERS = {}
CHART_SERVER_START_PORT = 8765
CHART_SERVER_LOCK = threading.Lock()

# Import chart server components
sys.path.insert(0, str(PROJECT_ROOT / "reportingCharts"))
from run_charts import build_handler


def find_available_port(start_port=CHART_SERVER_START_PORT):
    """Find an available port starting from start_port"""
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError("No available ports found for chart server")


def start_chart_server_thread(version_id):
    """Start chart server for a specific version in a daemon thread"""
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
    
    # Start server in daemon thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Store server info
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
    """Stop chart server for a specific version"""
    with CHART_SERVER_LOCK:
        if version_id not in CHART_SERVERS:
            return False
        
        server_info = CHART_SERVERS[version_id]
    
    try:
        # Shutdown the server
        server_info['server'].shutdown()
        # Wait for thread to finish with timeout
        server_info['thread'].join(timeout=5)
    except Exception as e:
        print(f"Error stopping chart server for {version_id}: {e}")
    finally:
        # Always remove from dict
        with CHART_SERVER_LOCK:
            if version_id in CHART_SERVERS:
                del CHART_SERVERS[version_id]
        return True


def cleanup_all_chart_servers():
    """Stop all running chart servers"""
    print("Cleaning up all chart servers...")
    with CHART_SERVER_LOCK:
        version_ids = list(CHART_SERVERS.keys())
    
    for version_id in version_ids:
        stop_chart_server(version_id)
    
    print("Chart server cleanup complete")


def kill_process_on_port(port):
    current_pid = os.getpid()
    try:
        result = subprocess.run(
            ["lsof", "-t", f"-i:{port}"],
            capture_output=True,
            text=True,
            check=False
        )
        pids = [
            int(pid.strip())
            for pid in result.stdout.splitlines()
            if pid.strip().isdigit() and int(pid.strip()) != current_pid
        ]
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
        if pids:
            time.sleep(0.3)
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    continue
                except PermissionError:
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


# Register cleanup on exit
atexit.register(cleanup_all_chart_servers)


@app.route('/')
def index():
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('frontend', filename)

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "gtm-planning-engine"})

@app.route('/api/config-schema', methods=['GET'])
def get_config_schema():
    """Returns structure of config.yaml for form generation"""
    try:
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": f"Failed to load config schema: {str(e)}"}), 500

@app.route('/api/config/defaults', methods=['GET'])
def get_config_defaults():
    """Returns default config values for reset functionality"""
    try:
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f)
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": f"Failed to load config defaults: {str(e)}"}), 500

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
                except:
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
    
    import pandas as pd
    df = pd.read_csv(results_file)
    return jsonify(df.to_dict(orient='records'))

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

@app.route('/api/run-plan', methods=['POST'])
def run_plan():
    try:
        data = request.json or {}
        description = data.get('description', 'API Run')
        annual_target = data.get('annual_target', 188000000)
        mode = data.get('mode', 'full')
        optimizer = data.get('optimizer', 'greedy')
        auto_start_charts = data.get('auto_start_charts', True)

        with open(CONFIG_FILE) as f:
            base_config = yaml.safe_load(f) or {}

        config_updates = data.get('config_updates')
        if isinstance(config_updates, dict) and config_updates:
            runtime_config = deep_merge_dict(base_config, config_updates)
        else:
            runtime_config = deep_merge_dict(base_config, {
                "targets": {"annual_target": annual_target},
                "allocation": {"optimizer_mode": optimizer}
            })

        runtime_config.setdefault("targets", {})
        runtime_config["targets"]["annual_target"] = annual_target
        runtime_config.setdefault("allocation", {})
        runtime_config["allocation"]["optimizer_mode"] = optimizer
        normalize_cash_cycle_distribution_keys(runtime_config)

        temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        temp_config.write(yaml.safe_dump(runtime_config, sort_keys=False))
        temp_config.close()
        
        try:
            cmd = [sys.executable, 'run_plan.py', '--config', temp_config.name, '--description', description, '--mode', mode]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(PROJECT_ROOT)
            )
            
            if result.returncode != 0:
                return jsonify({
                    "error": "Plan execution failed",
                    "details": result.stderr[-500:] if result.stderr else result.stdout[-500:]
                }), 500
            
            version_id = None
            for line in result.stdout.split('\n'):
                if 'Version' in line and 'saved to' in line:
                    path_match = re.search(r"versions/(v\d+)", line)
                    if path_match:
                        version_id = path_match.group(1)
                        break
                    number_match = re.search(r"Version\s+(\d+)", line)
                    if number_match:
                        version_id = normalize_version_id(number_match.group(1))
                        break
            
            if not version_id:
                versions = sorted(VERSIONS_DIR.glob('v*'), key=lambda x: x.stat().st_mtime, reverse=True)
                if versions:
                    version_id = versions[0].name
            
            if version_id:
                summary_file = VERSIONS_DIR / version_id / 'summary.json'
                validation_file = VERSIONS_DIR / version_id / 'validation_report.json'
                
                summary = {}
                validation_passed = False
                
                if summary_file.exists():
                    with open(summary_file) as f:
                        summary = json.load(f)
                
                if validation_file.exists():
                    with open(validation_file) as f:
                        validation = json.load(f)
                        validation_passed = validation.get('passed', False)
                
                response = {
                    "version_id": version_id,
                    "summary": summary,
                    "validation_passed": validation_passed,
                    "stdout": result.stdout
                }
                
                # Auto-start chart server if requested
                if auto_start_charts:
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
            else:
                return jsonify({
                    "error": "Could not determine version ID",
                    "stdout": result.stdout
                }), 500
                
        finally:
            os.unlink(temp_config.name)
            
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Plan execution timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/charts/server/<version_id>', methods=['POST'])
def start_chart_server(version_id):
    """Start chart server for specific version"""
    try:
        version_id = normalize_version_id(version_id)
        version_dir = VERSIONS_DIR / version_id
        if not version_dir.exists():
            return jsonify({"error": f"Version {version_id} not found"}), 404
        
        # Check if server is already running
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
    """Stop chart server for version"""
    try:
        version_id = normalize_version_id(version_id)
        success = stop_chart_server(version_id)
        if success:
            return jsonify({
                "status": "stopped",
                "version_id": version_id
            })
        else:
            return jsonify({
                "status": "not_running",
                "version_id": version_id
            }), 404
    except Exception as e:
        return jsonify({"error": f"Failed to stop chart server: {str(e)}"}), 500


@app.route('/api/charts/server/<version_id>/status')
def chart_server_status(version_id):
    """Check if chart server is running"""
    try:
        version_id = normalize_version_id(version_id)
        with CHART_SERVER_LOCK:
            if version_id in CHART_SERVERS:
                server_info = CHART_SERVERS[version_id]
                # Check if thread is alive
                is_alive = server_info['thread'].is_alive()
                if is_alive:
                    return jsonify({
                        "status": "running",
                        "version_id": version_id,
                        "port": server_info['port'],
                        "url": server_info['url']
                    })
                else:
                    # Clean up dead server entry
                    del CHART_SERVERS[version_id]
                    return jsonify({
                        "status": "stopped",
                        "version_id": version_id
                    })
            else:
                return jsonify({
                    "status": "not_found",
                    "version_id": version_id
                }), 404
    except Exception as e:
        return jsonify({"error": f"Failed to check chart server status: {str(e)}"}), 500


@app.route('/api/charts/servers', methods=['GET'])
def list_chart_servers():
    """List all running chart servers"""
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
                    # Collect dead servers for cleanup
                    dead_servers.append(version_id)
            
            # Clean up dead server entries
            for version_id in dead_servers:
                del CHART_SERVERS[version_id]
            
            return jsonify({
                "servers": servers,
                "count": len(servers)
            })
    except Exception as e:
        return jsonify({"error": f"Failed to list chart servers: {str(e)}"}), 500

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
        <a href="/">← Back to Main</a>
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
