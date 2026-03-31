from __future__ import annotations

import argparse
import csv
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Example folder path structure: /Users/shourjosmac/Documents/Claude/Projects/Interview prep/GTM_Planning_Engine/versions/v010/
DEFAULT_DATA_DIR = PROJECT_ROOT / "versions" / "v010"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone CSV tab and Plotly chart viewer")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Absolute or relative folder path containing CSV files",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind local server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind local server")
    return parser.parse_args()


def load_csv_payload(csv_path: Path) -> dict[str, object]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({column: (row.get(column) or "") for column in columns})
    return {"file_name": csv_path.name, "columns": columns, "rows": rows}


def build_handler(data_dir: Path) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format_string: str, *args: object) -> None:
            return

        def _send_json(self, payload: dict[str, object], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str, status: int = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(build_index_html(str(data_dir)))
                return

            if parsed.path == "/api/files":
                csv_files = sorted(path.name for path in data_dir.glob("*.csv"))
                self._send_json({"data_dir": str(data_dir), "files": csv_files})
                return

            if parsed.path == "/api/csv":
                query = parse_qs(parsed.query)
                requested_file = (query.get("file") or [""])[0]
                if not requested_file.endswith(".csv"):
                    self._send_json({"error": "Invalid CSV filename"}, status=HTTPStatus.BAD_REQUEST)
                    return

                safe_name = Path(requested_file).name
                csv_path = (data_dir / safe_name).resolve()
                if csv_path.parent != data_dir.resolve():
                    self._send_json({"error": "Unsafe file path"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if not csv_path.exists():
                    self._send_json({"error": f"CSV file not found: {safe_name}"}, status=HTTPStatus.NOT_FOUND)
                    return

                try:
                    payload = load_csv_payload(csv_path)
                except Exception as exc:
                    self._send_json({"error": f"Failed to read CSV: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                    return

                self._send_json(payload)
                return

            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    return RequestHandler


def build_index_html(data_dir: str) -> str:
    escaped_data_dir = json.dumps(data_dir)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CSV Reporting Charts</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {{
      --bg: #f8fafc;
      --surface: #ffffff;
      --border: #e5e7eb;
      --text: #111827;
      --muted: #6b7280;
      --accent: #2563eb;
      --accent-2: #0d9488;
      --accent-3: #d97706;
      --accent-4: #7c3aed;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 18px;
      background: var(--bg);
      color: var(--text);
      font-family: Verdana, Geneva, Tahoma, sans-serif;
    }}
    .container {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
    }}
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .meta {{
      color: var(--muted);
      font-size: 12px;
      word-break: break-all;
    }}
    button, select {{
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      border-radius: 8px;
      padding: 6px 10px;
      font-size: 12px;
      font-family: inherit;
    }}
    button.primary {{
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }}
    .tabs {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .tab {{
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 10px;
      background: #fff;
      font-size: 12px;
      cursor: pointer;
    }}
    .tab.active {{
      border-color: var(--accent);
      color: #fff;
      background: var(--accent);
    }}
    .table_wrap {{
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      max-height: 360px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
      background: #fff;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 7px 8px;
      text-align: left;
      white-space: nowrap;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #f3f4f6;
      z-index: 1;
    }}
    .table_controls {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 8px;
      gap: 10px;
      flex-wrap: wrap;
      font-size: 12px;
      color: var(--muted);
    }}
    .chart_panel {{
      width: 60vw;
      min-width: 680px;
      max-width: 1200px;
      margin: 0 auto;
    }}
    .chart_controls {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 8px;
      font-size: 12px;
    }}
    .series_pills {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }}
    .pill {{
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 4px 8px;
      background: #fff;
      font-size: 11px;
      display: inline-flex;
      gap: 6px;
      align-items: center;
    }}
    .pill button {{
      border: none;
      padding: 0;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-size: 11px;
    }}
    .status {{
      font-size: 12px;
      color: var(--muted);
      min-height: 18px;
    }}
    @media (max-width: 860px) {{
      .chart_panel {{
        width: 100%;
        min-width: unset;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="panel header">
      <div>
        <div style="font-size: 16px; font-weight: 700;">CSV Reporting Charts</div>
        <div class="meta">Data directory: <span id="dataDir"></span></div>
      </div>
      <button id="reloadBtn" class="primary">Reload Files</button>
    </div>

    <div class="panel">
      <div id="tabBar" class="tabs"></div>
      <div class="status" id="status"></div>
    </div>

    <div class="panel">
      <div id="tableContainer" class="table_wrap"></div>
      <div class="table_controls">
        <div id="tableInfo"></div>
        <div>
          <button id="prevPageBtn">Prev</button>
          <span id="pageText"></span>
          <button id="nextPageBtn">Next</button>
        </div>
      </div>
    </div>

    <div class="panel chart_panel">
      <div class="chart_controls">
        <label>X-axis:</label>
        <select id="xSelect"></select>
        <label>Y column:</label>
        <select id="ySelect"></select>
        <label><input type="checkbox" id="includeNonNumeric" /> Include non-numeric</label>
        <button id="addSeriesBtn" class="primary">Add Series</button>
        <button id="clearSeriesBtn">Clear Series</button>
      </div>
      <div class="series_pills" id="seriesPills"></div>
      <div id="chart" style="height: 280px;"></div>
    </div>
  </div>

  <script>
    const page_size = 20;
    const data_dir = {escaped_data_dir};
    const palette = ['#2563eb', '#0d9488', '#d97706', '#7c3aed', '#db2777', '#4b5563'];

    const state = {{
      files: [],
      active_file: null,
      rows: [],
      columns: [],
      page: 1,
      selected_series: [],
    }};

    const tab_bar = document.getElementById('tabBar');
    const status_el = document.getElementById('status');
    const table_container = document.getElementById('tableContainer');
    const table_info = document.getElementById('tableInfo');
    const page_text = document.getElementById('pageText');
    const x_select = document.getElementById('xSelect');
    const y_select = document.getElementById('ySelect');
    const include_non_numeric = document.getElementById('includeNonNumeric');
    const series_pills = document.getElementById('seriesPills');

    document.getElementById('dataDir').textContent = data_dir;
    document.getElementById('reloadBtn').addEventListener('click', load_files);
    document.getElementById('prevPageBtn').addEventListener('click', () => {{
      if (state.page > 1) {{
        state.page -= 1;
        render_table();
      }}
    }});
    document.getElementById('nextPageBtn').addEventListener('click', () => {{
      const total_pages = Math.max(1, Math.ceil(state.rows.length / page_size));
      if (state.page < total_pages) {{
        state.page += 1;
        render_table();
      }}
    }});
    document.getElementById('addSeriesBtn').addEventListener('click', add_series);
    document.getElementById('clearSeriesBtn').addEventListener('click', () => {{
      state.selected_series = [];
      render_series_pills();
      render_chart();
    }});
    include_non_numeric.addEventListener('change', render_column_selectors);
    x_select.addEventListener('change', render_chart);

    async function fetch_json(url) {{
      const response = await fetch(url);
      if (!response.ok) {{
        throw new Error(`Request failed (${{response.status}})`);
      }}
      return response.json();
    }}

    function set_status(message) {{
      status_el.textContent = message;
    }}

    function normalize_column_name(column_name) {{
      return column_name.toLowerCase().replaceAll(/[^a-z0-9]+/g, '_');
    }}

    function is_percentage_column(column_name) {{
      const normalized = normalize_column_name(column_name);
      const percentage_names = new Set(['share', 'win_rate', 'shrinkage_rate', 'mentoring_tax', 'effective_cw_rate']);
      return percentage_names.has(normalized) || normalized.includes('win_rate') || normalized.includes('cw_rate');
    }}

    function is_zero_decimal_column(column_name) {{
      const normalized = normalize_column_name(column_name);
      return normalized.startsWith('hc_')
        || normalized.includes('revenue')
        || normalized.includes('pipeline')
        || normalized.includes('saos')
        || normalized.includes('bookings');
    }}

    function parse_numeric_or_null(raw_value) {{
      const parsed = Number((raw_value ?? '').toString().trim());
      if (!Number.isFinite(parsed)) {{
        return null;
      }}
      return parsed;
    }}

    function round_value(value, decimals) {{
      const factor = 10 ** decimals;
      return Math.round(value * factor) / factor;
    }}

    function format_number(value, decimals) {{
      return value.toLocaleString(undefined, {{
        minimumFractionDigits: 0,
        maximumFractionDigits: decimals,
      }});
    }}

    function format_numeric_for_display(column_name, numeric_value) {{
      if (is_percentage_column(column_name)) {{
        const percent_value = round_value(numeric_value * 100, 2);
        return `${{format_number(percent_value, 2)}}%`;
      }}
      if (is_zero_decimal_column(column_name)) {{
        const rounded_whole = round_value(numeric_value, 0);
        return format_number(rounded_whole, 0);
      }}
      const rounded_two = round_value(numeric_value, 2);
      return format_number(rounded_two, 2);
    }}

    function get_chart_numeric_value(column_name, numeric_value) {{
      if (is_percentage_column(column_name)) {{
        return round_value(numeric_value * 100, 2);
      }}
      if (is_zero_decimal_column(column_name)) {{
        return round_value(numeric_value, 0);
      }}
      return round_value(numeric_value, 2);
    }}

    function format_cell_value(column_name, raw_value) {{
      const parsed = parse_numeric_or_null(raw_value);
      if (parsed === null) {{
        return (raw_value ?? '').toString();
      }}
      return format_numeric_for_display(column_name, parsed);
    }}

    function is_numeric_column(column_name) {{
      let valid_count = 0;
      for (const row of state.rows) {{
        const value = (row[column_name] ?? '').toString().trim();
        if (value === '') continue;
        const number_value = Number(value);
        if (Number.isFinite(number_value)) {{
          valid_count += 1;
          continue;
        }}
        return false;
      }}
      return valid_count > 0;
    }}

    function get_numeric_columns() {{
      return state.columns.filter(is_numeric_column);
    }}

    function get_candidate_y_columns() {{
      const numeric_columns = get_numeric_columns();
      if (include_non_numeric.checked) {{
        const non_numeric_columns = state.columns.filter(col => !numeric_columns.includes(col));
        return [...numeric_columns, ...non_numeric_columns];
      }}
      return numeric_columns;
    }}

    function render_tabs() {{
      tab_bar.innerHTML = '';
      for (const file_name of state.files) {{
        const button = document.createElement('button');
        button.className = `tab ${{state.active_file === file_name ? 'active' : ''}}`;
        button.textContent = file_name;
        button.addEventListener('click', () => load_file(file_name));
        tab_bar.appendChild(button);
      }}
    }}

    function render_table() {{
      if (!state.columns.length) {{
        table_container.innerHTML = '<div style="padding:10px;color:#6b7280;">No table data available.</div>';
        table_info.textContent = '';
        page_text.textContent = '';
        return;
      }}
      const total_pages = Math.max(1, Math.ceil(state.rows.length / page_size));
      if (state.page > total_pages) {{
        state.page = total_pages;
      }}
      const start = (state.page - 1) * page_size;
      const end = start + page_size;
      const visible_rows = state.rows.slice(start, end);

      let table_html = '<table><thead><tr>';
      for (const col of state.columns) {{
        table_html += `<th>${{escape_html(col)}}</th>`;
      }}
      table_html += '</tr></thead><tbody>';
      for (const row of visible_rows) {{
        table_html += '<tr>';
        for (const col of state.columns) {{
          table_html += `<td>${{escape_html(format_cell_value(col, row[col]))}}</td>`;
        }}
        table_html += '</tr>';
      }}
      table_html += '</tbody></table>';
      table_container.innerHTML = table_html;

      table_info.textContent = `Rows: ${{state.rows.length}} | Showing ${{visible_rows.length}}`;
      page_text.textContent = `Page ${{state.page}} / ${{total_pages}}`;
    }}

    function render_column_selectors() {{
      x_select.innerHTML = '';
      for (const column_name of state.columns) {{
        const option = document.createElement('option');
        option.value = column_name;
        option.textContent = column_name;
        x_select.appendChild(option);
      }}

      if (state.columns.length && !state.columns.includes(x_select.value)) {{
        x_select.value = state.columns[0];
      }}

      const y_columns = get_candidate_y_columns();
      y_select.innerHTML = '';
      for (const column_name of y_columns) {{
        const option = document.createElement('option');
        option.value = column_name;
        option.textContent = column_name;
        y_select.appendChild(option);
      }}

      state.selected_series = state.selected_series.filter(col => state.columns.includes(col));
      if (!state.selected_series.length && y_columns.length) {{
        state.selected_series = [y_columns[0]];
      }}
      render_series_pills();
      render_chart();
    }}

    function add_series() {{
      const selected = y_select.value;
      if (!selected) return;
      if (!state.selected_series.includes(selected)) {{
        state.selected_series.push(selected);
        render_series_pills();
        render_chart();
      }}
    }}

    function render_series_pills() {{
      series_pills.innerHTML = '';
      for (const series_name of state.selected_series) {{
        const pill = document.createElement('span');
        pill.className = 'pill';
        pill.innerHTML = `${{escape_html(series_name)}} <button title="Remove">✕</button>`;
        const remove_button = pill.querySelector('button');
        remove_button.addEventListener('click', () => {{
          state.selected_series = state.selected_series.filter(col => col !== series_name);
          render_series_pills();
          render_chart();
        }});
        series_pills.appendChild(pill);
      }}
    }}

    function build_trace(column_name, index, use_dual_axis) {{
      const x_values = state.rows.map(row => row[x_select.value] ?? '');
      const numeric = is_numeric_column(column_name);

      if (numeric) {{
        const y_values = state.rows.map(row => {{
          const parsed = parse_numeric_or_null(row[column_name]);
          if (parsed === null) return null;
          return get_chart_numeric_value(column_name, parsed);
        }});
        const hover_values = state.rows.map(row => {{
          const parsed = parse_numeric_or_null(row[column_name]);
          if (parsed === null) return '';
          return format_numeric_for_display(column_name, parsed);
        }});
        const use_right_axis = use_dual_axis && is_percentage_column(column_name);
        return {{
          x: x_values,
          y: y_values,
          customdata: hover_values,
          type: 'scatter',
          mode: 'lines+markers',
          name: column_name,
          line: {{ color: palette[index % palette.length], width: 2 }},
          marker: {{ size: 5 }},
          yaxis: use_right_axis ? 'y2' : 'y',
          hovertemplate: `<b>${{escape_html(column_name)}}</b><br>${{escape_html(x_select.value)}}=%{{x}}<br>value=%{{customdata}}<extra></extra>`,
        }};
      }}

      const value_to_index = new Map();
      const encoded_y = state.rows.map(row => {{
        const category = (row[column_name] ?? '').toString();
        if (!value_to_index.has(category)) {{
          value_to_index.set(category, value_to_index.size);
        }}
        return value_to_index.get(category);
      }});

      const original_values = state.rows.map(row => (row[column_name] ?? '').toString());
      return {{
        x: x_values,
        y: encoded_y,
        customdata: original_values,
        type: 'scatter',
        mode: 'lines+markers',
        name: `${{column_name}} (categorical)`,
        line: {{ color: palette[index % palette.length], width: 2, dash: 'dot' }},
        marker: {{ size: 5 }},
        hovertemplate: `<b>${{escape_html(column_name)}} (categorical)</b><br>${{escape_html(x_select.value)}}=%{{x}}<br>value=%{{customdata}}<extra></extra>`,
      }};
    }}

    function render_chart() {{
      const chart_node = document.getElementById('chart');
      if (!state.rows.length || !state.columns.length || !x_select.value || !state.selected_series.length) {{
        Plotly.newPlot(chart_node, [], {{
          margin: {{ l: 40, r: 20, t: 24, b: 40 }},
          paper_bgcolor: '#ffffff',
          plot_bgcolor: '#ffffff',
          font: {{ family: 'Verdana, sans-serif', size: 11 }},
          xaxis: {{ title: '' }},
          yaxis: {{ title: '' }},
          annotations: [{{ text: 'Select series to plot', x: 0.5, y: 0.5, showarrow: false }}],
        }}, {{ responsive: true }});
        return;
      }}

      const has_percent_numeric = state.selected_series.some(
        col => is_numeric_column(col) && is_percentage_column(col)
      );
      const has_non_percent_numeric = state.selected_series.some(
        col => is_numeric_column(col) && !is_percentage_column(col)
      );
      const use_dual_axis = has_percent_numeric && has_non_percent_numeric;
      const traces = state.selected_series.map((column_name, index) => build_trace(column_name, index, use_dual_axis));
      const has_non_numeric = state.selected_series.some(col => !is_numeric_column(col));
      const layout = {{
        margin: {{ l: 46, r: 20, t: 24, b: 40 }},
        paper_bgcolor: '#ffffff',
        plot_bgcolor: '#ffffff',
        font: {{ family: 'Verdana, sans-serif', size: 11, color: '#111827' }},
        xaxis: {{
          title: x_select.value,
          gridcolor: '#e5e7eb',
          zerolinecolor: '#e5e7eb',
        }},
        yaxis: {{
          title: has_non_numeric ? 'Value / Encoded Category Index' : 'Value',
          gridcolor: '#e5e7eb',
          zerolinecolor: '#e5e7eb',
        }},
        yaxis2: {{
          title: 'Percentage',
          overlaying: 'y',
          side: 'right',
          showgrid: false,
          tickformat: '.2f',
          ticksuffix: '%',
          visible: use_dual_axis,
        }},
        legend: {{
          orientation: 'h',
          yanchor: 'bottom',
          y: 1.01,
          xanchor: 'left',
          x: 0,
        }},
        hovermode: 'x unified',
      }};

      Plotly.newPlot(chart_node, traces, layout, {{
        responsive: true,
        displaylogo: false,
      }});
    }}

    function escape_html(value) {{
      return value
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }}

    async function load_file(file_name) {{
      try {{
        set_status(`Loading ${{file_name}}...`);
        const payload = await fetch_json(`/api/csv?file=${{encodeURIComponent(file_name)}}`);
        state.active_file = file_name;
        state.columns = payload.columns ?? [];
        state.rows = payload.rows ?? [];
        state.page = 1;
        state.selected_series = [];
        render_tabs();
        render_table();
        render_column_selectors();
        set_status(`Loaded ${{file_name}}`);
      }} catch (error) {{
        set_status(`Failed to load file: ${{error.message}}`);
        state.columns = [];
        state.rows = [];
        state.selected_series = [];
        render_tabs();
        render_table();
        render_column_selectors();
      }}
    }}

    async function load_files() {{
      try {{
        set_status('Loading file list...');
        const payload = await fetch_json('/api/files');
        state.files = payload.files ?? [];
        if (!state.files.length) {{
          state.active_file = null;
          state.columns = [];
          state.rows = [];
          state.selected_series = [];
          render_tabs();
          render_table();
          render_column_selectors();
          set_status('No CSV files found in selected folder.');
          return;
        }}

        const next_file = state.files.includes(state.active_file) ? state.active_file : state.files[0];
        await load_file(next_file);
      }} catch (error) {{
        set_status(`Failed to load files: ${{error.message}}`);
      }}
    }}

    load_files();
  </script>
</body>
</html>"""


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()

    if not data_dir.exists() or not data_dir.is_dir():
        raise SystemExit(f"Invalid --data-dir: {data_dir}")

    handler_class = build_handler(data_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler_class)
    print(f"Serving CSV viewer on http://{args.host}:{args.port}/")
    print(f"Reading CSV files from: {data_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
