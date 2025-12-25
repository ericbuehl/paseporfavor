# Santa Monica Parking Permit Automation

Automated web service for requesting Santa Monica temporary parking permits with CAPTCHA solving and optional automatic printing.

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your Google credentials and account details

# 2. Start the service
docker-compose up

# 3. Open browser
http://localhost:1886
```

## Configuration

Edit `.env` file with **required** fields:

```bash
# Google Cloud Vision API (REQUIRED)
GOOGLE_CREDENTIALS_FILE=./your-credentials.json

# Santa Monica account details (REQUIRED)
ACCOUNT_NUMBER=your-account-number
ZIP_CODE=90405
LAST_NAME=YourLastName
EMAIL=your-email@example.com

# Optional settings
PRINTER_IP=192.168.1.100
PRINTER_NAME=AutoPrinter
DRY_RUN=true  # Set false for production
```

**Note:**
- The application will not start if required fields are missing.
- Auto-print can be toggled per request in the web UI (defaults to ON).

### Getting Google Cloud Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Vision API**
3. Create a **Service Account** with "Cloud Vision API User" role
4. Download the JSON key file
5. Set path in `.env`: `GOOGLE_CREDENTIALS_FILE=./your-credentials.json`

## Features

- **Real-time streaming UI** - Watch progress as permits are generated
- **Automatic CAPTCHA solving** - 100% success rate with Google Vision API
- **Multi-step form handling** - Navigates complete 7-step workflow
- **Auto-printing** - Sends permits directly to network printer (optional)
- **Dry-run mode** - Test without actually submitting permit requests

## How It Works

1. User visits web interface at `http://localhost:1886`
2. Enters number of permits needed
3. Service fetches Santa Monica permit form
4. Solves CAPTCHA using Google Vision API
5. Navigates through multi-step form process
6. Downloads generated permit PDFs
7. Optionally prints to configured network printer

In **DRY_RUN mode**, the service stops before final submission and prints a test PDF to verify printer connectivity.

## Logs

View detailed logs including CUPS print job activity:

```bash
# All logs
docker-compose logs -f

# CUPS-specific
docker exec permit-automation tail -f /var/log/cups/error_log
```
