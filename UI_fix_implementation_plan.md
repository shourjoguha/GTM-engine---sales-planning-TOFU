# UI Fix Implementation Plan

## Objective
- Implement all requested UI fixes across Configuration and Reports & Charts.
- Preserve existing behavior and data compatibility.
- Deliver in phased steps with verification after each phase.

## Phase Checklist
- [x] Phase 1: Tooltip behavior and placement
  - [x] Render tooltip trigger inline with field labels.
  - [x] Remove section clipping behavior for tooltips.
  - [x] Add dynamic viewport-aware tooltip placement.
- [x] Phase 2: Targets improvements
  - [x] Show seasonality values as percentages in UI.
  - [x] Add live seasonality total indicator and error state when total exceeds 100%.
  - [x] Add conditional Planning Mode controls for rolling and locked modes.
- [x] Phase 3: AE hiring tranches
  - [x] Add editable hiring tranche inputs.
  - [x] Support add/remove tranche actions.
  - [x] Keep tranche row horizontally visible/scrollable.
- [x] Phase 4: What-if scenarios editing
  - [x] Rename scenario labels in UI:
    - [x] EOR pricing pressure → Pricing pressure
    - [x] Q2 attrition spike → Attrition Spike
    - [x] Marketing budget cut → Channel budget cut
  - [x] Expose perturbation values as editable fields.
  - [x] Support extendable key/value perturbation maps.
- [x] Phase 5: Backend config mapping
  - [x] Build robust form payload to nested config mapping in /api/run-plan.
  - [x] Ensure defaults and backward compatibility are preserved.
- [x] Phase 6: Recommendations in Reports & Charts
  - [x] Load recovery_analysis.json for selected version.
  - [x] Render dedicated Recommendations section above Analytics.
  - [x] Handle missing recovery file gracefully.
- [x] Phase 7: Reports page sizing
  - [x] Make Reports & Charts fill available viewport height like Configuration page.
  - [x] Avoid clipping in embedded report/table areas.
- [x] Phase 8: Validation and regression checks
  - [x] Run targeted smoke checks for config submission and chart rendering.
  - [x] Validate no regression in version loading and chart server flow.
  - [x] Mark all completed phases.

## Notes
- Use YAML-backed values only, no hardcoded business constants.
- Keep naming conventions and existing architecture patterns.
- Avoid breaking current API contracts and file formats.
