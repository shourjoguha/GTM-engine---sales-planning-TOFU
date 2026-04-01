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
DEFAULT_DATA_DIR = PROJECT_ROOT / "versions" / "v011"
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
  <title>Analytics Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    html {{ font-size: 16px; }}
    body {{
      margin: 0;
      padding: 0;
      background: #f9fafb;
      color: #111827;
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      -webkit-font-smoothing: antialiased;
      line-height: 1.5;
    }}

    /* ── Header ── */
    .header {{
      background: #fff;
      border-bottom: 1px solid #e5e7eb;
      position: sticky;
      top: 0;
      z-index: 40;
    }}
    .header-inner {{
      width: 100%;
      padding: 18px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .header-left {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .header-icon {{
      background: #4f46e5;
      padding: 10px;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .header-icon svg {{ width: 24px; height: 24px; color: #fff; }}
    .header-title {{
      font-size: 29px;
      font-weight: 600;
      color: #111827;
      letter-spacing: -0.01em;
    }}
    .header-right {{
      display: flex;
      align-items: center;
      gap: 18px;
    }}
    .header-badge {{
      font-size: 21px;
      font-weight: 500;
      color: #6b7280;
    }}
    .reload-btn {{
      background: #4f46e5;
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 10px 20px;
      font-size: 21px;
      font-weight: 500;
      font-family: inherit;
      cursor: pointer;
      transition: background 0.15s;
    }}
    .reload-btn:hover {{ background: #4338ca; }}

    /* ── Main ── */
    .main {{
      width: 100%;
      padding: 32px 32px 100px;
    }}

    /* ── Tab Bar ── */
    .tab-bar {{
      display: flex;
      flex-wrap: wrap;
      background: rgba(229,231,235,0.5);
      padding: 5px;
      border-radius: 14px;
      margin-bottom: 32px;
      gap: 3px;
      width: fit-content;
    }}
    .tab-btn {{
      position: relative;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 20px;
      font-size: 21px;
      font-weight: 500;
      font-family: inherit;
      border: none;
      background: transparent;
      color: #6b7280;
      border-radius: 10px;
      cursor: pointer;
      transition: color 0.2s, background 0.2s;
      white-space: nowrap;
    }}
    .tab-btn:hover {{ color: #374151; }}
    .tab-btn.active {{
      background: #fff;
      color: #111827;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .tab-btn svg {{ width: 20px; height: 20px; flex-shrink: 0; }}

    /* ── Status ── */
    .status {{
      font-size: 21px;
      color: #6b7280;
      min-height: 28px;
      margin-bottom: 10px;
    }}

    /* ── Charts Grid ── */
    .charts-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 28px;
    }}
    @media (max-width: 900px) {{
      .charts-grid {{ grid-template-columns: 1fr; }}
    }}

    /* ── Chart Card ── */
    .chart-card {{
      background: #fff;
      padding: 24px;
      border-radius: 14px;
      border: 1px solid #e5e7eb;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
      display: flex;
      flex-direction: column;
      position: relative;
      animation: card-in 0.35s ease-out;
    }}
    @keyframes card-in {{
      from {{ opacity: 0; transform: translateY(16px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    /* ── Remove button — always visible, top-right corner ── */
    .remove-btn {{
      position: absolute;
      top: 14px;
      right: 14px;
      padding: 7px;
      border: 2px solid #d1d5db;
      background: #fff;
      border-radius: 8px;
      cursor: pointer;
      color: #6b7280;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
      z-index: 5;
    }}
    .remove-btn:hover {{
      color: #ef4444;
      border-color: #ef4444;
      background: #fef2f2;
    }}
    .remove-btn svg {{ width: 20px; height: 20px; stroke-width: 2.5; }}

    .chart-card-header {{
      display: flex;
      justify-content: flex-start;
      align-items: flex-start;
      margin-bottom: 20px;
      padding-right: 52px;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .chart-axis-selectors {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      flex: 1;
    }}
    .axis-select {{
      appearance: none;
      -webkit-appearance: none;
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      color: #111827;
      font-size: 21px;
      font-weight: 600;
      font-family: inherit;
      border-radius: 8px;
      padding: 8px 36px 8px 14px;
      cursor: pointer;
      transition: background 0.15s;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 10px center;
    }}
    .axis-select:hover {{ background-color: #f3f4f6; }}
    .axis-select:focus {{ outline: none; box-shadow: 0 0 0 2px rgba(79,70,229,0.2); }}
    .axis-select-y {{
      background-color: #eef2ff;
      border-color: #e0e7ff;
      color: #4338ca;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%234338ca' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
    }}
    .axis-select-y:hover {{ background-color: #e0e7ff; }}
    .axis-vs {{ font-size: 21px; font-weight: 500; color: #9ca3af; }}

    .chart-type-toggle {{
      display: flex;
      background: #f3f4f6;
      padding: 4px;
      border-radius: 10px;
      gap: 3px;
    }}
    .type-btn {{
      padding: 8px;
      border: none;
      background: transparent;
      border-radius: 7px;
      cursor: pointer;
      color: #6b7280;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
    }}
    .type-btn:hover {{ color: #374151; }}
    .type-btn.active {{
      background: #fff;
      color: #4f46e5;
      box-shadow: 0 1px 2px rgba(0,0,0,0.08);
    }}
    .type-btn svg {{ width: 20px; height: 20px; }}
    .chart-area {{ flex: 1; min-height: 340px; width: 100%; }}

    /* ── Add Chart Row ── */
    .add-chart-row {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: center;
      padding: 8px 0 4px;
    }}
    .add-chart-inline-btn {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 32px;
      background: #fff;
      border: 2px dashed #c7d2fe;
      border-radius: 12px;
      color: #4f46e5;
      font-size: 21px;
      font-weight: 600;
      font-family: inherit;
      cursor: pointer;
      transition: all 0.2s;
      width: 100%;
      justify-content: center;
    }}
    .add-chart-inline-btn:hover {{
      background: #eef2ff;
      border-color: #818cf8;
    }}
    .add-chart-inline-btn svg {{ width: 22px; height: 22px; }}

    /* ── Empty State ── */
    .empty-charts {{
      background: #fff;
      border: 2px dashed #d1d5db;
      border-radius: 14px;
      padding: 60px;
      text-align: center;
      grid-column: 1 / -1;
    }}
    .empty-charts-icon {{
      width: 56px; height: 56px;
      background: #f9fafb;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 18px;
    }}
    .empty-charts-icon svg {{ width: 28px; height: 28px; color: #9ca3af; }}
    .empty-charts h3 {{ font-size: 22px; font-weight: 500; color: #111827; margin: 0 0 6px; }}
    .empty-charts p {{ font-size: 19px; color: #6b7280; margin: 0; }}

    /* ── FAB ── */
    .fab {{
      position: fixed;
      bottom: 36px;
      right: 36px;
      background: #4f46e5;
      color: #fff;
      border: none;
      width: 64px;
      height: 64px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: 0 8px 24px rgba(79,70,229,0.35);
      z-index: 50;
      transition: transform 0.15s, background 0.15s, box-shadow 0.15s, width 0.25s, border-radius 0.25s, padding 0.25s;
      overflow: hidden;
    }}
    .fab:hover {{
      transform: scale(1.04);
      background: #4338ca;
      box-shadow: 0 12px 32px rgba(79,70,229,0.45);
      width: auto;
      border-radius: 32px;
      padding: 0 24px;
      gap: 10px;
    }}
    .fab svg {{ width: 28px; height: 28px; flex-shrink: 0; }}
    .fab-label {{
      max-width: 0;
      overflow: hidden;
      white-space: nowrap;
      font-size: 21px;
      font-weight: 600;
      font-family: inherit;
      transition: max-width 0.3s, margin-left 0.3s;
    }}
    .fab:hover .fab-label {{ max-width: 140px; margin-left: 4px; }}

    /* ── Data Table ── */
    .table-panel {{
      background: #fff;
      border-radius: 14px;
      border: 1px solid #e5e7eb;
      box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
      overflow: hidden;
      margin-top: 36px;
    }}
    .table-header {{
      padding: 20px 28px;
      border-bottom: 1px solid #f3f4f6;
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: rgba(249,250,251,0.5);
    }}
    .table-title {{ font-size: 22px; font-weight: 600; color: #111827; }}
    .table-row-badge {{
      font-size: 19px;
      font-weight: 500;
      color: #6b7280;
      background: #f3f4f6;
      padding: 5px 12px;
      border-radius: 7px;
    }}
    .table-pagination {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 28px;
      border-bottom: 1px solid #f3f4f6;
      font-size: 19px;
      color: #6b7280;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .table-pagination-bottom {{
      border-bottom: none;
      border-top: 1px solid #f3f4f6;
    }}
    .pagination-info span {{ font-weight: 600; color: #111827; }}
    .pagination-controls {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .page-size-label {{ font-size: 19px; color: #6b7280; }}
    .page-size-select {{
      appearance: none;
      -webkit-appearance: none;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 6px 32px 6px 12px;
      font-size: 19px;
      font-family: inherit;
      background: #fff;
      color: #111827;
      cursor: pointer;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 8px center;
    }}
    .page-btn {{
      padding: 8px;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      background: #fff;
      color: #6b7280;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s;
    }}
    .page-btn:hover:not(:disabled) {{ background: #f9fafb; color: #111827; }}
    .page-btn:disabled {{ opacity: 0.4; cursor: not-allowed; }}
    .page-btn svg {{ width: 22px; height: 22px; }}
    .table-scroll {{
      overflow: auto;
      max-height: 600px;
    }}
    .table-scroll::-webkit-scrollbar {{ width: 8px; height: 8px; }}
    .table-scroll::-webkit-scrollbar-track {{ background: transparent; }}
    .table-scroll::-webkit-scrollbar-thumb {{ background: #e5e7eb; border-radius: 99px; }}
    .table-scroll::-webkit-scrollbar-thumb:hover {{ background: #d1d5db; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 19px;
      white-space: nowrap;
    }}
    thead {{ position: sticky; top: 0; z-index: 2; }}
    th {{
      text-align: left;
      padding: 14px 28px;
      font-size: 18px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: #6b7280;
      background: rgba(249,250,251,0.97);
      border-bottom: 1px solid #e5e7eb;
      backdrop-filter: blur(4px);
    }}
    td {{
      padding: 13px 28px;
      color: #374151;
    }}
    tbody tr {{
      border-bottom: 1px solid #f3f4f6;
      transition: background 0.1s;
    }}
    tbody tr:hover {{ background: rgba(238,242,255,0.4); }}
    tbody tr:last-child {{ border-bottom: none; }}
  </style>
</head>
<body>
  <!-- Header -->
  <header class="header">
    <div class="header-inner">
      <div class="header-left">
        <div class="header-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
        </div>
        <h1 class="header-title">Analytics</h1>
      </div>
      <div class="header-right">
        <span class="header-badge" id="chartCount">0 Charts</span>
        <button class="reload-btn" id="reloadBtn">Reload Files</button>
      </div>
    </div>
  </header>

  <!-- Main Content -->
  <main class="main">
    <div id="tabBar" class="tab-bar"></div>
    <div class="status" id="status"></div>

    <!-- Charts Grid -->
    <div id="chartsGrid" class="charts-grid"></div>

    <!-- Data Table -->
    <div class="table-panel" id="tablePanel">
      <div class="table-header">
        <span class="table-title">Raw Data View</span>
        <span class="table-row-badge" id="rowBadge">0 rows</span>
      </div>
      <div class="table-pagination" id="paginationTop">
        <div class="pagination-info" id="pageInfoTop"></div>
        <div class="pagination-controls">
          <span class="page-size-label">Rows per page:</span>
          <select class="page-size-select" id="pageSizeSelect">
            <option value="20">20</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
          <button class="page-btn" id="prevTop" title="Previous page">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <button class="page-btn" id="nextTop" title="Next page">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
          </button>
        </div>
      </div>
      <div class="table-scroll" id="tableScroll"></div>
      <div class="table-pagination table-pagination-bottom" id="paginationBottom">
        <div class="pagination-info" id="pageInfoBottom"></div>
        <div class="pagination-controls">
          <button class="page-btn" id="prevBottom" title="Previous page">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
          </button>
          <button class="page-btn" id="nextBottom" title="Next page">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
          </button>
        </div>
      </div>
    </div>
  </main>

  <!-- FAB -->
  <button class="fab" id="addChartBtn" title="Add new chart">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
    <span class="fab-label">Add Chart</span>
  </button>

  <script>
    /* ── SVG Icon Templates ── */
    const ICONS = {{
      file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>',
      bar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
      line: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
      area: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 20h18L15 8l-4 6-4-4-4 10z"/></svg>',
      box: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="8" width="12" height="8" rx="1"/><line x1="12" y1="4" x2="12" y2="8"/><line x1="12" y1="16" x2="12" y2="20"/><line x1="9" y1="4" x2="15" y2="4"/><line x1="9" y1="20" x2="15" y2="20"/></svg>',
      scatter: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="7" cy="17" r="2"/><circle cx="17" cy="7" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="5" cy="9" r="2"/><circle cx="19" cy="16" r="2"/></svg>',
      trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>',
      empty: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>',
      plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    }};

    /* ── Color Palette (dark-to-light blue) ── */
    const palette = ['#1e3a5f', '#1e40af', '#2563eb', '#3b82f6', '#60a5fa', '#93c5fd', '#bfdbfe'];

    /* ── State ── */
    const data_dir = {escaped_data_dir};
    const state = {{
      files: [],
      active_file: null,
      rows: [],
      columns: [],
      page: 1,
      page_size: 20,
      charts: [],
      chart_counter: 0,
    }};

    /* ── DOM Refs ── */
    const tab_bar = document.getElementById('tabBar');
    const status_el = document.getElementById('status');
    const charts_grid = document.getElementById('chartsGrid');
    const chart_count_el = document.getElementById('chartCount');
    const table_scroll = document.getElementById('tableScroll');
    const row_badge = document.getElementById('rowBadge');
    const page_size_select = document.getElementById('pageSizeSelect');

    /* ── Events ── */
    document.getElementById('reloadBtn').addEventListener('click', load_files);
    document.getElementById('addChartBtn').addEventListener('click', add_chart);
    page_size_select.addEventListener('change', () => {{
      state.page_size = parseInt(page_size_select.value, 10);
      state.page = 1;
      render_table();
    }});
    for (const suffix of ['Top', 'Bottom']) {{
      document.getElementById('prev' + suffix).addEventListener('click', () => {{
        if (state.page > 1) {{ state.page -= 1; render_table(); }}
      }});
      document.getElementById('next' + suffix).addEventListener('click', () => {{
        const total = Math.max(1, Math.ceil(state.rows.length / state.page_size));
        if (state.page < total) {{ state.page += 1; render_table(); }}
      }});
    }}

    /* ── Helpers ── */
    async function fetch_json(url) {{
      const r = await fetch(url);
      if (!r.ok) throw new Error(`Request failed (${{r.status}})`);
      return r.json();
    }}

    function set_status(msg) {{ status_el.textContent = msg; }}

    function escape_html(v) {{
      return v.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
    }}

    function normalize_column_name(c) {{
      return c.toLowerCase().replaceAll(/[^a-z0-9]+/g, '_');
    }}

    function is_percentage_column(c) {{
      const n = normalize_column_name(c);
      const pcts = new Set(['share','win_rate','shrinkage_rate','mentoring_tax','effective_cw_rate']);
      return pcts.has(n) || n.includes('win_rate') || n.includes('cw_rate');
    }}

    function is_zero_decimal_column(c) {{
      const n = normalize_column_name(c);
      return n.startsWith('hc_') || n.includes('revenue') || n.includes('pipeline') || n.includes('saos') || n.includes('bookings');
    }}

    function parse_numeric_or_null(v) {{
      const p = Number((v ?? '').toString().trim());
      return Number.isFinite(p) ? p : null;
    }}

    function round_value(v, d) {{ const f = 10 ** d; return Math.round(v * f) / f; }}

    function format_number(v, d) {{
      return v.toLocaleString(undefined, {{ minimumFractionDigits: 0, maximumFractionDigits: d }});
    }}

    function format_numeric_for_display(col, val) {{
      if (is_percentage_column(col)) return `${{format_number(round_value(val * 100, 2), 2)}}%`;
      if (is_zero_decimal_column(col)) return format_number(round_value(val, 0), 0);
      return format_number(round_value(val, 2), 2);
    }}

    function get_chart_numeric_value(col, val) {{
      if (is_percentage_column(col)) return round_value(val * 100, 2);
      if (is_zero_decimal_column(col)) return round_value(val, 0);
      return round_value(val, 2);
    }}

    function format_cell_value(col, raw) {{
      const p = parse_numeric_or_null(raw);
      return p === null ? (raw ?? '').toString() : format_numeric_for_display(col, p);
    }}

    function is_numeric_column(col) {{
      let count = 0;
      for (const row of state.rows) {{
        const v = (row[col] ?? '').toString().trim();
        if (v === '') continue;
        if (!Number.isFinite(Number(v))) return false;
        count++;
      }}
      return count > 0;
    }}

    function get_numeric_columns() {{ return state.columns.filter(is_numeric_column); }}

    function update_chart_count() {{
      const n = state.charts.length;
      chart_count_el.textContent = `${{n}} ${{n === 1 ? 'Chart' : 'Charts'}}`;
    }}

    /* ── Tabs ── */
    function render_tabs() {{
      tab_bar.innerHTML = '';
      for (const f of state.files) {{
        const btn = document.createElement('button');
        btn.className = `tab-btn ${{state.active_file === f ? 'active' : ''}}`;
        btn.innerHTML = `${{ICONS.file}}<span>${{escape_html(f)}}</span>`;
        btn.addEventListener('click', () => load_file(f));
        tab_bar.appendChild(btn);
      }}
    }}

    /* ── Chart Cards ── */
    function add_chart() {{
      const numeric = get_numeric_columns();
      const x_key = state.columns[0] || '';
      const y_key = numeric[0] || state.columns[0] || '';
      state.chart_counter++;
      const config = {{
        id: `chart-${{state.chart_counter}}-${{Date.now()}}`,
        type: 'bar',
        xAxisKey: x_key,
        yAxisKey: y_key,
      }};
      state.charts.push(config);
      render_charts_grid();
    }}

    function remove_chart(id) {{
      const el = document.getElementById(id);
      if (el) {{
        const plot_el = el.querySelector('.chart-plot');
        if (plot_el) Plotly.purge(plot_el);
      }}
      state.charts = state.charts.filter(c => c.id !== id);
      render_charts_grid();
    }}

    function update_chart_config(id, key, value) {{
      state.charts = state.charts.map(c => c.id === id ? {{ ...c, [key]: value }} : c);
      render_single_chart(state.charts.find(c => c.id === id));
    }}

    function render_charts_grid() {{
      /* Purge existing plots */
      for (const el of charts_grid.querySelectorAll('.chart-plot')) Plotly.purge(el);
      charts_grid.innerHTML = '';

      if (!state.charts.length) {{
        charts_grid.innerHTML = `
          <div class="empty-charts">
            <div class="empty-charts-icon">${{ICONS.empty}}</div>
            <h3>No charts yet</h3>
            <p>Click the button below or the + button to add a visualization.</p>
          </div>
          <div class="add-chart-row">
            <button class="add-chart-inline-btn" id="addChartInline">
              ${{ICONS.plus}} Add Chart
            </button>
          </div>`;
        document.getElementById('addChartInline').addEventListener('click', add_chart);
        update_chart_count();
        return;
      }}

      for (const cfg of state.charts) {{
        charts_grid.appendChild(build_chart_card(cfg));
      }}

      /* Add Chart inline button spans full width below all chart rows */
      const add_row = document.createElement('div');
      add_row.className = 'add-chart-row';
      add_row.innerHTML = `<button class="add-chart-inline-btn" id="addChartInline">${{ICONS.plus}} Add Chart</button>`;
      charts_grid.appendChild(add_row);
      document.getElementById('addChartInline').addEventListener('click', add_chart);

      update_chart_count();

      /* Render all plots after DOM is ready */
      requestAnimationFrame(() => {{
        for (const cfg of state.charts) render_single_chart(cfg);
      }});
    }}

    function build_chart_card(cfg) {{
      const card = document.createElement('div');
      card.className = 'chart-card';
      card.id = cfg.id;

      const numeric = get_numeric_columns();
      const all_cols = state.columns;

      const x_options = all_cols.map(c => `<option value="${{escape_html(c)}}" ${{c === cfg.xAxisKey ? 'selected' : ''}}>${{escape_html(c)}}</option>`).join('');
      const y_options = numeric.map(c => `<option value="${{escape_html(c)}}" ${{c === cfg.yAxisKey ? 'selected' : ''}}>${{escape_html(c)}}</option>`).join('');

      const types = ['bar', 'line', 'area', 'scatter', 'box'];

      card.innerHTML = `
        <button class="remove-btn" title="Remove chart">${{ICONS.trash}}</button>
        <div class="chart-card-header">
          <div class="chart-axis-selectors">
            <select class="axis-select axis-select-x">${{x_options}}</select>
            <span class="axis-vs">vs</span>
            <select class="axis-select axis-select-y">${{y_options}}</select>
          </div>
          <div class="chart-type-toggle">
            ${{types.map(t => `<button class="type-btn ${{cfg.type === t ? 'active' : ''}}" data-type="${{t}}" title="${{t.charAt(0).toUpperCase() + t.slice(1)}} Chart">${{ICONS[t]}}</button>`).join('')}}
          </div>
        </div>
        <div class="chart-area"><div class="chart-plot" style="width:100%;height:100%;"></div></div>`;

      /* Events */
      card.querySelector('.axis-select-x').addEventListener('change', (e) => update_chart_config(cfg.id, 'xAxisKey', e.target.value));
      card.querySelector('.axis-select-y').addEventListener('change', (e) => update_chart_config(cfg.id, 'yAxisKey', e.target.value));
      card.querySelector('.remove-btn').addEventListener('click', () => remove_chart(cfg.id));
      for (const btn of card.querySelectorAll('.type-btn')) {{
        btn.addEventListener('click', () => {{
          for (const b of card.querySelectorAll('.type-btn')) b.classList.remove('active');
          btn.classList.add('active');
          update_chart_config(cfg.id, 'type', btn.dataset.type);
        }});
      }}
      return card;
    }}

    function render_single_chart(cfg) {{
      if (!cfg) return;
      const card = document.getElementById(cfg.id);
      if (!card) return;
      const plot_el = card.querySelector('.chart-plot');

      if (!state.rows.length || !cfg.xAxisKey || !cfg.yAxisKey) {{
        Plotly.newPlot(plot_el, [], {{
          margin: {{ l: 56, r: 20, t: 20, b: 56 }},
          paper_bgcolor: '#fff', plot_bgcolor: '#fff',
          font: {{ family: "'Inter', sans-serif", size: 16 }},
          annotations: [{{ text: 'No data', x: 0.5, y: 0.5, showarrow: false, font: {{ color: '#9ca3af', size: 18 }} }}],
        }}, {{ responsive: true, displaylogo: false }});
        return;
      }}

      const x_vals = state.rows.map(r => r[cfg.xAxisKey] ?? '');
      const numeric_y = is_numeric_column(cfg.yAxisKey);
      const numeric_x = is_numeric_column(cfg.xAxisKey);

      /* Determine if x-axis labels are long strings that need rotation */
      const sample_x = x_vals.slice(0, 10);
      const needs_rotation = sample_x.some(v => String(v).length > 6);
      const tick_angle = needs_rotation ? -40 : 0;
      const bottom_margin = needs_rotation ? 90 : 56;

      const common_layout = {{
        margin: {{ l: 64, r: 20, t: 20, b: bottom_margin }},
        paper_bgcolor: '#fff',
        plot_bgcolor: '#fff',
        font: {{ family: "'Inter', sans-serif", size: 16, color: '#374151' }},
        xaxis: {{
          title: {{ text: cfg.xAxisKey, font: {{ size: 17, color: '#6b7280' }} }},
          gridcolor: '#f3f4f6',
          zerolinecolor: '#e5e7eb',
          tickfont: {{ size: 15, color: '#6b7280' }},
          tickangle: tick_angle,
          automargin: true,
        }},
        yaxis: {{
          title: {{ text: cfg.yAxisKey, font: {{ size: 17, color: '#6b7280' }} }},
          gridcolor: '#f3f4f6',
          zerolinecolor: '#e5e7eb',
          tickfont: {{ size: 15, color: '#6b7280' }},
          automargin: true,
        }},
        legend: {{ orientation: 'h', y: 1.1, x: 0, font: {{ size: 15 }} }},
        hovermode: 'closest',
      }};

      let traces = [];

      if (cfg.type === 'box') {{
        if (numeric_y) {{
          const y_vals = state.rows.map(r => {{
            const p = parse_numeric_or_null(r[cfg.yAxisKey]);
            return p === null ? null : get_chart_numeric_value(cfg.yAxisKey, p);
          }}).filter(v => v !== null);
          traces = [{{
            y: y_vals,
            x: x_vals,
            type: 'box',
            name: cfg.yAxisKey,
            marker: {{ color: palette[2] }},
            line: {{ color: palette[1] }},
            fillcolor: palette[5] + '80',
          }}];
        }}
      }} else if (cfg.type === 'scatter') {{
        /* For scatter: x numeric vs y numeric */
        const x_num = state.rows.map(r => {{
          const p = parse_numeric_or_null(r[cfg.xAxisKey]);
          return p === null ? null : get_chart_numeric_value(cfg.xAxisKey, p);
        }});
        const y_num = state.rows.map(r => {{
          const p = parse_numeric_or_null(r[cfg.yAxisKey]);
          return p === null ? null : get_chart_numeric_value(cfg.yAxisKey, p);
        }});
        const hover_x = state.rows.map(r => {{
          const p = parse_numeric_or_null(r[cfg.xAxisKey]);
          return p === null ? String(r[cfg.xAxisKey] ?? '') : format_numeric_for_display(cfg.xAxisKey, p);
        }});
        const hover_y = state.rows.map(r => {{
          const p = parse_numeric_or_null(r[cfg.yAxisKey]);
          return p === null ? '' : format_numeric_for_display(cfg.yAxisKey, p);
        }});
        traces = [{{
          x: numeric_x ? x_num : x_vals,
          y: y_num,
          customdata: hover_y.map((hy, i) => [hover_x[i], hy]),
          type: 'scatter',
          mode: 'markers',
          name: `${{cfg.xAxisKey}} vs ${{cfg.yAxisKey}}`,
          marker: {{ color: palette[2], size: 9, opacity: 0.75, line: {{ color: palette[1], width: 1 }} }},
          hovertemplate: `${{escape_html(cfg.xAxisKey)}}: %{{customdata[0]}}<br>${{escape_html(cfg.yAxisKey)}}: %{{customdata[1]}}<extra></extra>`,
        }}];
        /* Override hovermode for scatter */
        common_layout.hovermode = 'closest';
      }} else {{
        const y_vals = state.rows.map(r => {{
          const p = parse_numeric_or_null(r[cfg.yAxisKey]);
          return p === null ? null : get_chart_numeric_value(cfg.yAxisKey, p);
        }});
        const hover = state.rows.map(r => {{
          const p = parse_numeric_or_null(r[cfg.yAxisKey]);
          return p === null ? '' : format_numeric_for_display(cfg.yAxisKey, p);
        }});

        if (cfg.type === 'bar') {{
          traces = [{{
            x: x_vals, y: y_vals, customdata: hover,
            type: 'bar',
            name: cfg.yAxisKey,
            marker: {{ color: palette[2], line: {{ color: palette[1], width: 1 }} }},
            hovertemplate: `<b>${{escape_html(cfg.yAxisKey)}}</b><br>%{{x}}<br>%{{customdata}}<extra></extra>`,
          }}];
          common_layout.hovermode = 'x unified';
        }} else if (cfg.type === 'line') {{
          traces = [{{
            x: x_vals, y: y_vals, customdata: hover,
            type: 'scatter', mode: 'lines',
            name: cfg.yAxisKey,
            line: {{ color: palette[2], width: 2.5, shape: 'spline' }},
            hovertemplate: `<b>${{escape_html(cfg.yAxisKey)}}</b><br>%{{x}}<br>%{{customdata}}<extra></extra>`,
          }}];
          common_layout.hovermode = 'x unified';
        }} else if (cfg.type === 'area') {{
          traces = [{{
            x: x_vals, y: y_vals, customdata: hover,
            type: 'scatter', mode: 'lines',
            fill: 'tozeroy',
            fillcolor: palette[5] + '55',
            name: cfg.yAxisKey,
            line: {{ color: palette[2], width: 2.5, shape: 'spline' }},
            hovertemplate: `<b>${{escape_html(cfg.yAxisKey)}}</b><br>%{{x}}<br>%{{customdata}}<extra></extra>`,
          }}];
          common_layout.hovermode = 'x unified';
        }}
      }}

      Plotly.newPlot(plot_el, traces, common_layout, {{
        responsive: true,
        displaylogo: false,
        displayModeBar: false,
      }});
    }}

    /* ── Data Table ── */
    function render_table() {{
      if (!state.columns.length) {{
        table_scroll.innerHTML = '<div style="padding:28px;color:#6b7280;font-size:19px;">No table data available.</div>';
        row_badge.textContent = '0 rows';
        update_pagination_info();
        return;
      }}
      row_badge.textContent = `${{state.rows.length}} rows`;

      const total_pages = Math.max(1, Math.ceil(state.rows.length / state.page_size));
      if (state.page > total_pages) state.page = total_pages;
      const start = (state.page - 1) * state.page_size;
      const end = Math.min(start + state.page_size, state.rows.length);
      const visible = state.rows.slice(start, end);

      let html = '<table><thead><tr>';
      for (const col of state.columns) html += `<th>${{escape_html(col)}}</th>`;
      html += '</tr></thead><tbody>';
      for (const row of visible) {{
        html += '<tr>';
        for (const col of state.columns) html += `<td>${{escape_html(format_cell_value(col, row[col]))}}</td>`;
        html += '</tr>';
      }}
      html += '</tbody></table>';
      table_scroll.innerHTML = html;

      update_pagination_info();
    }}

    function update_pagination_info() {{
      const total_pages = Math.max(1, Math.ceil(state.rows.length / state.page_size));
      const start = state.rows.length ? (state.page - 1) * state.page_size + 1 : 0;
      const end = Math.min(state.page * state.page_size, state.rows.length);
      const info_html = state.rows.length
        ? `Showing <span>${{start}}</span> to <span>${{end}}</span> of <span>${{state.rows.length}}</span> results`
        : 'No results';

      document.getElementById('pageInfoTop').innerHTML = info_html;
      document.getElementById('pageInfoBottom').innerHTML = info_html;

      for (const suffix of ['Top', 'Bottom']) {{
        document.getElementById('prev' + suffix).disabled = state.page <= 1;
        document.getElementById('next' + suffix).disabled = state.page >= total_pages;
      }}
    }}

    /* ── File Loading ── */
    async function load_file(file_name) {{
      try {{
        set_status(`Loading ${{file_name}}...`);
        const payload = await fetch_json(`/api/csv?file=${{encodeURIComponent(file_name)}}`);
        state.active_file = file_name;
        state.columns = payload.columns ?? [];
        state.rows = payload.rows ?? [];
        state.page = 1;
        state.charts = [];
        state.chart_counter = 0;
        render_tabs();
        render_table();
        /* Add two default charts */
        const numeric = get_numeric_columns();
        if (state.columns.length && numeric.length) {{
          state.chart_counter++;
          state.charts.push({{
            id: `chart-${{state.chart_counter}}-${{Date.now()}}`,
            type: 'bar',
            xAxisKey: state.columns[0],
            yAxisKey: numeric[0],
          }});
          if (numeric.length > 1) {{
            state.chart_counter++;
            state.charts.push({{
              id: `chart-${{state.chart_counter}}-${{Date.now() + 1}}`,
              type: 'line',
              xAxisKey: state.columns[0],
              yAxisKey: numeric[1],
            }});
          }}
        }}
        render_charts_grid();
        set_status(`Loaded ${{file_name}}`);
      }} catch (err) {{
        set_status(`Failed to load file: ${{err.message}}`);
        state.columns = [];
        state.rows = [];
        state.charts = [];
        render_tabs();
        render_table();
        render_charts_grid();
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
          state.charts = [];
          render_tabs();
          render_table();
          render_charts_grid();
          set_status('No CSV files found in selected folder.');
          return;
        }}
        const next = state.files.includes(state.active_file) ? state.active_file : state.files[0];
        await load_file(next);
      }} catch (err) {{
        set_status(`Failed to load files: ${{err.message}}`);
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
