# GTM Planning Engine - Frontend SPA

## Overview

This is the frontend Single Page Application (SPA) for the GTM Planning Engine. It provides a clean, modern interface for configuring and analyzing GTM planning scenarios.

## Features

- **Configuration Tab**: Dynamic form generation from config.yaml
- **Charts Tab**: Interactive visualization via run_charts.py
- **In-Window Loading**: Real-time progress updates during plan execution
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Auto-Switch**: Automatically switches to charts after plan completion

## Getting Started

### Prerequisites

- Python 3.7+
- Flask (for backend)
- Modern web browser (Chrome, Firefox, Safari)

### Installation

1. Ensure backend is running:
   ```bash
   python app.py
   ```

2. Open browser to:
   ```
   http://127.0.0.1:8000/
   ```

## File Structure

```
frontend/
├── index.html                    # Main SPA entry point
├── css/
│   └── styles.css                # Complete styling
├── js/
│   ├── app.js                   # Application bootstrap
│   ├── tab_manager.js           # Tab switching logic
│   ├── config_form.js           # Configuration form
│   ├── chart_viewer.js          # Charts viewer
│   ├── loading_overlay.js       # Loading animation
│   └── api_client.js            # API communication
└── assets/
    └── loading.svg               # Loading animation placeholder
```

## Usage

### Running a Plan

1. Navigate to **Configuration** tab
2. Fill in the form fields with your desired configuration
3. Click **Run Plan** button
4. Wait for plan execution (loading overlay will show progress)
5. Automatically switch to **Reports & Charts** tab
6. View interactive charts with your plan results

### Viewing Previous Versions

1. Navigate to **Reports & Charts** tab
2. Use the version selector dropdown to choose a version
3. Charts will automatically load for the selected version
4. Use fullscreen mode for detailed analysis

### Resetting to Defaults

1. Navigate to **Configuration** tab
2. Click **Reset to Defaults** button
3. All form values will be restored from config.yaml

## Customization

### Custom Loading Animation

To replace the default loading animation with your custom SVG:

1. Open `frontend/index.html`
2. Find the `<div class="loading-spinner">` element
3. Replace the SVG content with your custom animation
4. Ensure it has class `loading-spinner`

Or use the API:
```javascript
LoadingOverlay.setCustomAnimation(yourSVGElement);
```

### Styling

All styling is in `frontend/css/styles.css`. Key theme variables:
```css
:root {
  --primary: #4f46e5;
  --primary-hover: #4338ca;
  --bg-page: #f9fafb;
  --bg-card: #ffffff;
  --border: #e5e7eb;
  --text-primary: #111827;
  --text-secondary: #6b7280;
}
```

## Troubleshooting

### Charts Not Loading

- Check that the backend is running
- Verify chart server status via `/api/charts/server/<version_id>/status`
- Check browser console for errors
- Ensure no firewall is blocking the chart server port

### Form Validation Errors

- Seasonality weights must sum to 1.0
- Share floor must be less than share ceiling
- All required fields must be filled
- Values must be within valid ranges

### Performance Issues

- Clear browser cache
- Disable browser extensions temporarily
- Check network tab in developer tools for slow requests
- Ensure backend server has adequate resources

## Accessibility

- Keyboard navigation: Tab, Shift+Tab, Enter, Escape
- Screen reader support: ARIA labels and roles
- Focus management: Logical tab order
- Color contrast: WCAG AA compliant

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Development

### Building from Source

No build step required - the SPA uses vanilla HTML/CSS/JavaScript.

### Testing

Test files are provided:
- `frontend/test_loading_overlay.html` - Test loading overlay
- `frontend/test_chart_viewer.html` - Test charts viewer

## Support

For issues or questions, refer to the main project documentation or contact the development team.
