# Railway Deployment Guide for GTM Planning Engine

## Overview

This application has been packaged for Railway deployment with a Flask web interface that allows users to:
- Run planning scenarios with custom parameters
- View and compare different plan versions
- Download results and access interactive charts

## What's Been Added

### New Files
- `app.py` - Flask web application with REST API
- `Procfile` - Railway deployment configuration
- `runtime.txt` - Python version specification
- `Dockerfile` - Container configuration (optional)
- `.gitignore` - Properly configured to keep essential data
- `RAILWAY_DEPLOYMENT.md` - This deployment guide

### Modified Files
- `requirements.txt` - Added Flask dependency
- Created `.gitkeep` files for essential directories

## Data Management Strategy

### Files Kept in Git
- `data/raw/.gitkeep` - Ensures directory structure
- `data/raw/2025_actuals.csv` - Sample data file
- `versions/.gitkeep` - Ensures directory structure
- `config.yaml` - Configuration file

### Files Not in Git (Generated)
- `versions/v*` - Generated plan versions (except first few for demo)
- `data/raw/*.csv` - Additional data files (except sample)

### Railway Persistence
Railway's filesystem is ephemeral. For production:
1. **Use Railway Volumes** for persistent storage
2. **External storage** (S3, R2) for long-term data
3. **Database** for metadata storage

## Deployment Options

### Option 1: Railway Auto-Detection (Recommended - No Docker)

**Steps:**
1. Push code to GitHub
2. Go to Railway dashboard → New Project → Deploy from GitHub
3. Select your repository
4. Railway will auto-detect Python and use `Procfile`

**Configuration:**
- Set environment variable `PORT=8000` (Railway sets this automatically)
- Set `HOST=0.0.0.0` (default in app.py)

### Option 2: Docker Deployment

**Steps:**
1. Create Docker context for Railway:
   ```bash
   railway login
   railway init
   ```

2. Set Dockerfile in Railway dashboard:
   - Go to your service settings
   - Select "Dockerfile" as build method
   - Railway will use the provided Dockerfile

## Environment Variables

Set these in Railway dashboard:

| Variable | Value | Description |
|----------|---------|-------------|
| `PORT` | `8000` | Port for Flask app (Railway sets this) |
| `HOST` | `0.0.0.0` | Host binding (default) |
| `PYTHONUNBUFFERED` | `1` | Python output buffering |

## Web Application Features

### Main Interface (`/`)
- Form to run new planning scenarios
- Parameters: Description, Annual Target, Mode, Optimizer
- View list of available versions

### API Endpoints

| Endpoint | Method | Description |
|----------|---------|-------------|
| `/health` | GET | Health check |
| `/api/versions` | GET | List all plan versions |
| `/api/version/{id}/summary` | GET | Get version summary |
| `/api/version/{id}/results` | GET | Get version results (JSON) |
| `/api/version/{id}/download/{file}` | GET | Download specific file |
| `/api/run-plan` | POST | Run new planning scenario |
| `/viewer/{version_id}` | GET | Interactive chart viewer |

### Usage Example

```python
import requests

# Run a new plan
response = requests.post('https://your-app.railway.app/api/run-plan', json={
    'description': 'Q3 2026 Forecast',
    'annual_target': 200000000,
    'mode': 'full',
    'optimizer': 'solver'
})

result = response.json()
version_id = result['version_id']
print(f"Plan completed: Version {version_id}")
print(f"Bookings: ${result['summary']['total_bookings']:,}")
```

## Testing Locally

### Prerequisites
- Python 3.12
- Dependencies from `requirements.txt`

### Run Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Visit `http://localhost:8000` to access the web interface.

### Test the API
```bash
# Health check
curl http://localhost:8000/health

# Run a plan
curl -X POST http://localhost:8000/api/run-plan \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Test plan",
    "annual_target": 188000000,
    "mode": "full",
    "optimizer": "greedy"
  }'
```

## Railway-Specific Considerations

### Filesystem Persistence
Railway containers are ephemeral. Generated data in `versions/` will be lost on redeployment.

**Solutions:**
1. **Railway Volumes** (Recommended for small-scale)
   ```bash
   railway volume create plans-data
   # Mount to /app/versions in service settings
   ```

2. **External Storage** (Production)
   - AWS S3
   - Cloudflare R2
   - Azure Blob Storage

3. **Database Integration**
   - Store metadata in PostgreSQL
   - Store results as JSON/CSV in database

### Resource Limits
- **Free tier**: 512MB RAM, 0.5 vCPU
- **Starter**: 1GB RAM, 0.5 vCPU
- **Recommended for this app**: 2GB RAM, 1 vCPU

### Scaling
- **Web server**: Can scale horizontally
- **Background jobs**: Use Railway Jobs for long-running plans
- **Cron**: Use Railway Cron for scheduled runs

## Troubleshooting

### App Crashes Immediately
- Check logs: `railway logs`
- Ensure all dependencies are in `requirements.txt`
- Verify Python version in `runtime.txt`

### Plans Time Out
- Increase timeout in `app.py` (currently 300s)
- Upgrade to higher tier
- Use Railway Jobs for long-running tasks

### Data Persistence Issues
- Enable Railway Volumes
- Use external storage for results
- Implement database backup strategy

## Production Recommendations

1. **Authentication**: Add user authentication to web interface
2. **Rate Limiting**: Implement API rate limiting
3. **Monitoring**: Add error tracking (Sentry, LogRocket)
4. **Database**: Replace file-based storage with PostgreSQL
5. **CDN**: Use Cloudflare for static assets
6. **Backup**: Regular backups to external storage

## Cost Estimate

**Railway Pricing** (as of 2025):
- **Free tier**: $5/month credit
- **Starter**: $5/month (1GB RAM)
- **Standard**: $20/month (2GB RAM)
- **Pro**: $40/month (4GB RAM)

**Estimated monthly cost**: $5-20 depending on usage and persistence needs.

## Support

For issues specific to Railway:
- [Railway Documentation](https://docs.railway.app)
- [Railway Discord](https://discord.gg/railway)

For GTM Planning Engine issues:
- Check application logs
- Verify data files are present
- Test locally first before deploying
