# Minimal UI Spec: CSV Tabs + Plotly Charts

## Scope
- Standalone viewer with no edits to existing project code.
- Reads every CSV file from a user-provided folder.
- Shows each CSV in a tabbed table view.
- Provides an interactive Plotly line-chart panel below the table.

## Entry Point
- Main runner: `reportingCharts/run_charts.py`
- Single command run:
  - `python reportingCharts/run_charts.py`
  - Optional custom folder: `python reportingCharts/run_charts.py --data-dir "/absolute/path/to/folder"`

## Data Contract
- Input folder contains one or more `.csv` files.
- API surface (local server):
  - `GET /api/files` → list of CSV filenames.
  - `GET /api/csv?file=<filename>` → columns + rows for one CSV.

## UI Layout
- Single page, light theme, Verdana font.
- Top bar:
  - Data folder display.
  - Reload button.
- Tab bar:
  - One tab per CSV filename.
- Table panel:
  - Sticky header.
  - 20 rows per page.
  - Prev/Next page controls with page indicator.
- Chart panel:
  - Positioned below table.
  - Width about 60% of viewport, centered.
  - Compact height.

## Table Behavior
- Default tab: first CSV file.
- Default page size: 20 rows.
- If fewer than 20 rows, show available rows.
- Empty or unreadable file shows clear inline message.

## Chart Behavior
- Plotly interactive line chart with hover tooltips.
- X-axis:
  - User-selectable from all columns.
- Y-series:
  - Multi-select with Add Series and Clear Series.
  - Auto-detect numeric columns and prioritize them in selector.
  - Allow non-numeric columns to be selected intentionally.

## Non-Numeric Series Handling
- Numeric series:
  - Plotted directly as line traces.
- Non-numeric series:
  - Categorical values encoded to ordinal indices for plotting.
  - Hover displays original category text.
  - Trace name indicates categorical encoding.
  - Y-axis title switches to encoded-category label when needed.

## Visual Design
- Font: Verdana.
- Palette:
  - Background: `#f8fafc`
  - Surface: `#ffffff`
  - Border: `#e5e7eb`
  - Text: `#111827`
  - Muted text: `#6b7280`
  - Accent: `#2563eb`, `#0d9488`, `#d97706`, `#7c3aed`
- Clean, consistent spacing and simple controls.

## Validation Checklist
- All CSV files appear as tabs.
- Table paginates at exactly 20 rows per page.
- Chart renders with hover interactions.
- Numeric columns auto-identified.
- Non-numeric column can still be plotted when selected.
- Works for sample folder structure under `versions/v010`.
