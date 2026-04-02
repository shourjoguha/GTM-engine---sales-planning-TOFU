from flask import Flask, request, jsonify, send_from_directory, render_template_string
from pathlib import Path
import os
import json
import sys
import subprocess
import tempfile
import shutil
from datetime import datetime

app = Flask(__name__)

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"
VERSIONS_DIR = PROJECT_ROOT / "versions"
CONFIG_FILE = PROJECT_ROOT / "config.yaml"

@app.route('/')
def index():
    return render_template_string('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GTM Planning Engine</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1200px; margin: 50px auto; padding: 20px; }
        h1 { color: #333; }
        .container { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
        .section { background: #f9f9f9; padding: 20px; border-radius: 8px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        input, select, textarea { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        button { background: #007bff; color: white; padding: 12px 24px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background: #0056b3; }
        .result { margin-top: 20px; padding: 15px; background: #d4edda; border-radius: 4px; display: none; }
        .error { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 4px; margin-top: 10px; }
        .version-list { margin-top: 20px; }
        .version-item { padding: 10px; margin: 5px 0; background: white; border-left: 3px solid #007bff; }
        a { color: #007bff; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h1>🎯 GTM Planning Engine</h1>
    
    <div class="container">
        <div class="section">
            <h2>Run New Plan</h2>
            <form id="planForm">
                <div class="form-group">
                    <label for="description">Plan Description:</label>
                    <input type="text" id="description" name="description" placeholder="e.g., Q3 2026 Forecast" required>
                </div>
                
                <div class="form-group">
                    <label for="annual_target">Annual Target ($):</label>
                    <input type="number" id="annual_target" name="annual_target" value="188000000" step="1000000">
                </div>
                
                <div class="form-group">
                    <label for="mode">Mode:</label>
                    <select id="mode" name="mode">
                        <option value="full">Full Pipeline</option>
                        <option value="what-if">What-If Scenario</option>
                        <option value="adjustment">Mid-Cycle Adjustment</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="optimizer">Optimizer Mode:</label>
                    <select id="optimizer" name="optimizer">
                        <option value="greedy">Greedy (Fast)</option>
                        <option value="solver">Solver (Precise)</option>
                    </select>
                </div>
                
                <button type="submit">Run Plan</button>
            </form>
            <div id="result" class="result"></div>
            <div id="error" class="error" style="display:none;"></div>
        </div>
        
        <div class="section">
            <h2>Available Versions</h2>
            <div id="versions" class="version-list">
                <p>Loading versions...</p>
            </div>
            <div style="margin-top: 20px;">
                <button onclick="loadVersions()">Refresh Versions</button>
            </div>
        </div>
    </div>
    
    <script>
        async function loadVersions() {
            try {
                const response = await fetch('/api/versions');
                const data = await response.json();
                const container = document.getElementById('versions');
                
                if (data.versions.length === 0) {
                    container.innerHTML = '<p>No versions found. Run a plan to create one.</p>';
                    return;
                }
                
                container.innerHTML = data.versions.map(v => `
                    <div class="version-item">
                        <strong>Version ${v.id}</strong>: ${v.description}<br>
                        <small>Created: ${new Date(v.created * 1000).toLocaleString()}</small><br>
                        <a href="/api/version/${v.id}/summary">Summary</a> | 
                        <a href="/api/version/${v.id}/results">Results</a> |
                        <a href="/viewer/${v.id}">View Charts</a>
                    </div>
                `).join('');
            } catch (error) {
                container.innerHTML = '<p class="error">Failed to load versions.</p>';
            }
        }
        
        document.getElementById('planForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultDiv = document.getElementById('result');
            const errorDiv = document.getElementById('error');
            
            resultDiv.style.display = 'none';
            errorDiv.style.display = 'none';
            resultDiv.innerHTML = '<p>Running plan... This may take a few minutes.</p>';
            resultDiv.style.display = 'block';
            
            const formData = {
                description: document.getElementById('description').value,
                annual_target: parseInt(document.getElementById('annual_target').value),
                mode: document.getElementById('mode').value,
                optimizer: document.getElementById('optimizer').value
            };
            
            try {
                const response = await fetch('/api/run-plan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(formData)
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    resultDiv.innerHTML = `
                        <h3>✅ Plan Completed Successfully!</h3>
                        <p><strong>Version ID:</strong> ${data.version_id}</p>
                        <p><strong>Bookings:</strong> $${data.summary.total_bookings?.toLocaleString() || 'N/A'}</p>
                        <p><strong>SAOs:</strong> ${data.summary.total_saos?.toLocaleString() || 'N/A'}</p>
                        <p><strong>Validation:</strong> ${data.validation_passed ? '✅ PASS' : '❌ FAIL'}</p>
                        <a href="/viewer/${data.version_id}">View Results</a>
                    `;
                    loadVersions();
                } else {
                    throw new Error(data.error || 'Unknown error');
                }
            } catch (error) {
                resultDiv.style.display = 'none';
                errorDiv.textContent = 'Error: ' + error.message;
                errorDiv.style.display = 'block';
            }
        });
        
        loadVersions();
    </script>
</body>
</html>
''')

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "service": "gtm-planning-engine"})

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
                        'created': int(summary.get('timestamp', datetime.now().timestamp()))
                    })
                except:
                    pass
    return jsonify({"versions": versions})

@app.route('/api/version/<version_id>/summary', methods=['GET'])
def get_version_summary(version_id):
    summary_file = VERSIONS_DIR / version_id / 'summary.json'
    if not summary_file.exists():
        return jsonify({"error": "Version not found"}), 404
    
    with open(summary_file) as f:
        summary = json.load(f)
    
    return jsonify(summary)

@app.route('/api/version/<version_id>/results', methods=['GET'])
def get_version_results(version_id):
    results_file = VERSIONS_DIR / version_id / 'results.csv'
    if not results_file.exists():
        return jsonify({"error": "Results not found"}), 404
    
    import pandas as pd
    df = pd.read_csv(results_file)
    return jsonify(df.to_dict(orient='records'))

@app.route('/api/version/<version_id>/download/<filename>')
def download_version_file(version_id, filename):
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
        data = request.json
        description = data.get('description', 'API Run')
        annual_target = data.get('annual_target', 188000000)
        mode = data.get('mode', 'full')
        optimizer = data.get('optimizer', 'greedy')
        
        with open(CONFIG_FILE) as f:
            config_content = f.read()
        
        config_content = config_content.replace('annual_target: 188000000', f'annual_target: {annual_target}')
        config_content = config_content.replace('optimizer_mode: "solver"', f'optimizer_mode: "{optimizer}"')
        config_content = config_content.replace('optimizer_mode: "greedy"', f'optimizer_mode: "{optimizer}"')
        
        temp_config = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        temp_config.write(config_content)
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
                    version_id = line.split()[1]
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
                
                return jsonify({
                    "version_id": version_id,
                    "summary": summary,
                    "validation_passed": validation_passed,
                    "stdout": result.stdout
                })
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

@app.route('/viewer/<version_id>')
def viewer(version_id):
    version_dir = VERSIONS_DIR / version_id
    if not version_dir.exists():
        return f"Version {version_id} not found", 404
    
    from reportingCharts.run_charts import build_index_html, build_handler
    
    handler_class = build_handler(version_dir)
    
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
    </div>
    <iframe src="/viewer-iframe/{{ version_id }}/"></iframe>
</body>
</html>
''', version_id=version_id)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=True)
