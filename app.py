"""
FastAPI web service for Santa Monica parking permit automation.
"""

import asyncio
import json
import os
import re
import traceback
from collections.abc import AsyncGenerator
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import uvicorn
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from main import SantaMonicaPermitAutomation
from settings import settings

app = FastAPI(title="Santa Monica Permit Automation")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Static file version for cache busting
STATIC_VERSION = "2"

# HTML template inline (can move to separate file later)
HOME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="color-scheme" content="light dark">
    <title>Santa Monica Permit Request</title>
    <link rel="stylesheet" href="/static/styles.css?v={{ version }}">
</head>
<body class="home-container">
    <div class="container">
        <h1>
            Santa Monica Permit Request
        </h1>
        <div class="badges">
            {% if dry_run %}
            <span class="badge badge-warning">DRY-RUN MODE</span>
            {% endif %}
            <span class="badge badge-autoprint badge-enabled badge-toggle" id="autoPrintBadge">Auto-Print</span>
        </div>

        <form action="/generate" method="post" id="permitForm">
            <input type="hidden" id="autoPrint" name="auto_print" value="true">
            <input type="hidden" id="permits" name="permits" value="1">

            <div class="form-group">
                <div class="permit-stepper">
                    <button type="button" class="stepper-button stepper-down" id="decrementBtn">−</button>
                    <span class="permit-count" id="permitCount">1</span>
                    <button type="button" class="stepper-button stepper-up" id="incrementBtn">+</button>
                </div>
            </div>

            <button type="submit" class="go-button" id="goButton">Request & Print</button>
        </form>

        <button class="info-toggle" id="infoToggle">
            <span class="info-toggle-icon" id="infoToggleIcon">▼</span>
            <span>Account Details</span>
        </button>
        <div class="info" id="infoSection">
            <strong>Account:</strong> {{ account_number }}<br>
            <strong>Name:</strong> {{ last_name }}<br>
            <strong>Email:</strong> <!--email_off-->{{ email }}<!--/email_off-->
        </div>
    </div>

    <script>
        const autoPrintBadge = document.getElementById('autoPrintBadge');
        const autoPrintInput = document.getElementById('autoPrint');
        const goButton = document.getElementById('goButton');
        const permitsInput = document.getElementById('permits');
        const permitCount = document.getElementById('permitCount');
        const incrementBtn = document.getElementById('incrementBtn');
        const decrementBtn = document.getElementById('decrementBtn');
        const infoToggle = document.getElementById('infoToggle');
        const infoSection = document.getElementById('infoSection');
        const infoToggleIcon = document.getElementById('infoToggleIcon');

        // Info section toggle
        infoToggle.addEventListener('click', function() {
            infoSection.classList.toggle('expanded');
            infoToggleIcon.classList.toggle('expanded');
        });

        // Auto-print toggle
        autoPrintBadge.addEventListener('click', function() {
            const isEnabled = autoPrintInput.value === 'true';

            if (isEnabled) {
                autoPrintInput.value = 'false';
                autoPrintBadge.classList.remove('badge-enabled');
                autoPrintBadge.classList.add('badge-disabled');
                goButton.textContent = 'Request';
            } else {
                autoPrintInput.value = 'true';
                autoPrintBadge.classList.remove('badge-disabled');
                autoPrintBadge.classList.add('badge-enabled');
                goButton.textContent = 'Request & Print';
            }
        });

        // Permit stepper
        function updatePermitCount(value) {
            permitsInput.value = value;
            permitCount.textContent = value;

            // Disable/enable buttons based on limits
            decrementBtn.disabled = value <= 1;
            incrementBtn.disabled = value >= 5;
        }

        incrementBtn.addEventListener('click', function() {
            const current = parseInt(permitsInput.value);
            if (current < 5) {
                updatePermitCount(current + 1);
            }
        });

        decrementBtn.addEventListener('click', function() {
            const current = parseInt(permitsInput.value);
            if (current > 1) {
                updatePermitCount(current - 1);
            }
        });

        // Initialize button states
        updatePermitCount(1);
    </script>
</body>
</html>
"""

PROGRESS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="color-scheme" content="light dark">
    <title>Generating Permits...</title>
    <link rel="stylesheet" href="/static/styles.css?v={{ version }}">
</head>
<body class="progress-container">
    <div class="header">
        <h1><span class="spinner" id="spinner"></span>Generating Permits</h1>
    </div>

    <div class="main-status">
        <span class="status-emoji" id="statusEmoji">⏳</span>
        <div class="status-text" id="statusText">Connecting...</div>
        <div class="status-detail" id="statusDetail">Initializing request...</div>
        <button class="log-toggle" id="logToggle" style="display: none;">
            <span class="log-toggle-icon" id="toggleIcon">▼</span>
            <span>Show Detailed Log</span>
        </button>
        <div id="backButtonContainer"></div>
    </div>

    <div class="log-container" id="logContainer">
        <div id="log"></div>
    </div>

    <script>
        const log = document.getElementById('log');
        const statusEmoji = document.getElementById('statusEmoji');
        const statusText = document.getElementById('statusText');
        const statusDetail = document.getElementById('statusDetail');
        const logToggle = document.getElementById('logToggle');
        const logContainer = document.getElementById('logContainer');
        const toggleIcon = document.getElementById('toggleIcon');
        const spinner = document.getElementById('spinner');
        const backButtonContainer = document.getElementById('backButtonContainer');

        const eventSource = new EventSource('/stream?permits={{ permits }}&auto_print={{ auto_print }}');

        let lastMessageTime = Date.now();
        let hasError = false;

        // Show log toggle button after first message
        let firstMessage = true;

        logToggle.addEventListener('click', function() {
            logContainer.classList.toggle('expanded');
            toggleIcon.classList.toggle('expanded');
            logToggle.querySelector('span:last-child').textContent =
                logContainer.classList.contains('expanded') ? 'Hide Detailed Log' : 'Show Detailed Log';
        });

        eventSource.onmessage = function(event) {
            lastMessageTime = Date.now();
            const data = JSON.parse(event.data);

            if (firstMessage) {
                logToggle.style.display = 'inline-flex';
                firstMessage = false;
            }

            if (data.type === 'log') {
                const now = new Date();
                const timestamp = now.toTimeString().split(' ')[0];

                let className = 'log-line';
                if (data.message.includes('✓') || data.message.includes('Success')) {
                    className += ' success';
                } else if (data.message.includes('✗') || data.message.includes('Error')) {
                    className += ' error';
                    hasError = true;
                } else if (data.message.includes('[') && data.message.includes(']')) {
                    className += ' step';
                } else {
                    className += ' info';
                }

                log.innerHTML += `<div class="${className}"><span class="timestamp">${timestamp}</span>${data.message}</div>`;
                log.scrollTop = log.scrollHeight;
            } else if (data.type === 'status') {
                statusText.textContent = data.message;
                statusDetail.textContent = 'Processing...';
            } else if (data.type === 'complete') {
                if (hasError) {
                    statusEmoji.textContent = '❌';
                    statusText.textContent = 'Request Failed';
                    statusDetail.textContent = 'Click "Show Detailed Log" below to see what went wrong';
                    logToggle.classList.add('error-state');
                } else {
                    statusEmoji.textContent = '✅';
                    statusText.textContent = 'Success!';
                    statusDetail.textContent = data.message || 'Permits generated successfully';

                    // Add download links if files are available
                    if (data.files && data.files.length > 0) {
                        const downloadLinks = document.createElement('div');
                        downloadLinks.className = 'download-links';
                        data.files.forEach((filename) => {
                            const link = document.createElement('a');
                            link.href = `/download/${filename}`;
                            link.className = 'download-link';
                            link.textContent = `📄 Download Permit PDF`;
                            link.download = `santa-monica-permit.pdf`;
                            downloadLinks.appendChild(link);
                        });
                        backButtonContainer.appendChild(downloadLinks);
                    }
                }
                spinner.style.display = 'none';
                eventSource.close();
                if (keepAliveInterval) clearInterval(keepAliveInterval);

                // Add back button
                const backBtn = document.createElement('a');
                backBtn.href = '/';
                backBtn.className = 'back-button';
                backBtn.textContent = '← Back to Home';
                backButtonContainer.appendChild(backBtn);
            } else if (data.type === 'error') {
                statusEmoji.textContent = '❌';
                statusText.textContent = 'Error';
                statusDetail.textContent = data.message;
                spinner.style.display = 'none';
                hasError = true;
                logToggle.classList.add('error-state');
                eventSource.close();
                if (keepAliveInterval) clearInterval(keepAliveInterval);
            }
        };

        eventSource.onerror = function() {
            if (Date.now() - lastMessageTime > 2000) {
                statusEmoji.textContent = '❌';
                statusText.textContent = 'Connection Lost';
                statusDetail.textContent = 'The connection to the server was interrupted';
                spinner.style.display = 'none';
                hasError = true;
                eventSource.close();
                if (keepAliveInterval) clearInterval(keepAliveInterval);
            }
        };

        // Keep connection alive check
        const keepAliveInterval = setInterval(() => {
            if (Date.now() - lastMessageTime > 30000) {
                statusDetail.textContent = '⚠ No updates for 30 seconds...';
            }
        }, 5000);
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with permit request form."""
    dry_run = settings.dry_run
    account_number = settings.account_number
    last_name = settings.last_name
    # Use Cloudflare Access authenticated email if available, otherwise use settings
    email = request.headers.get("cf-access-authenticated-user-email", settings.email)

    # Simple template rendering
    html = HOME_TEMPLATE
    html = html.replace('{{ version }}', STATIC_VERSION)
    html = html.replace('{{ account_number }}', str(account_number))
    html = html.replace('{{ last_name }}', str(last_name))
    html = html.replace('{{ email }}', str(email))

    # Handle conditional dry_run badge
    if dry_run:
        html = html.replace('{% if dry_run %}', '').replace('{% endif %}', '', 1)
    else:
        # Remove the dry_run badge section
        start = html.find('{% if dry_run %}')
        end = html.find('{% endif %}', start) + len('{% endif %}')
        html = html[:start] + html[end:]

    return HTMLResponse(content=html)


@app.post("/generate", response_class=HTMLResponse)
async def generate_page(permits: int = Form(1), auto_print: str = Form("true")):
    """Progress page that streams permit generation."""
    html = PROGRESS_TEMPLATE.replace('{{ version }}', STATIC_VERSION)
    html = html.replace('{{ permits }}', str(permits))
    html = html.replace('{{ auto_print }}', auto_print)
    return HTMLResponse(content=html)


async def save_and_print_pdf(pdf_bytes: bytes, permit_id, auto_print: bool, automation, emit):
    """Save PDF and optionally print it. Yields log messages, then (temp_file, success)."""
    yield emit(f"  ✓ Downloaded PDF ({len(pdf_bytes)} bytes)", 'log')

    # Save to temporary file
    with NamedTemporaryFile(
        mode='wb',
        suffix='.pdf',
        prefix=f'permit_{permit_id}_',
        delete=False,
        dir='/tmp'
    ) as tmp_file:
        tmp_file.write(pdf_bytes)
        temp_file_path = tmp_file.name
        temp_file = Path(temp_file_path).name

        # Schedule deletion after 10 minutes
        async def cleanup():
            await asyncio.sleep(600)
            try:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            except Exception:
                pass
        asyncio.create_task(cleanup())

    yield emit(f"  ✓ Saved as {temp_file}", 'log')

    success = False
    if auto_print:
        yield emit(f"  📄 Printing to {settings.printer_name}...", 'log')
        success = await automation.print_pdf(pdf_bytes, settings.printer_name)
        yield emit("  ✓ Print job submitted successfully" if success else "  ✗ Print job failed", 'log')

    yield emit("", 'log')
    yield (temp_file, success)


async def generate_permits_stream(
    num_permits: int, auto_print: bool = True, user_email: str | None = None
) -> AsyncGenerator[str]:
    """
    Generator that yields Server-Sent Events with progress updates.

    Args:
        num_permits: Number of permits to generate
        auto_print: Whether to automatically print permits (default True)
        user_email: Override email (e.g. from Cloudflare Access), falls back to settings
    """

    async def emit(message: str, event_type: str = 'log', files: list[str] | None = None):
        """Emit a Server-Sent Event."""
        data = {'type': event_type, 'message': message}
        if files:
            data['files'] = files
        yield f"data: {json.dumps(data)}\n\n"

    # Use provided email or fall back to settings
    email = user_email or settings.email
    yield emit("=" * 60, 'log')
    if settings.dry_run:
        yield emit("DRY-RUN MODE - Test workflow without final submission", 'log')
    else:
        yield emit("Santa Monica Parking Permit Automation", 'log')
    yield emit("=" * 60, 'log')
    yield emit("", 'log')

    async with SantaMonicaPermitAutomation() as automation:
        # Step 1: Fetch initial form
        yield emit("[1/7] Fetching initial form...", 'log')
        yield emit("Fetching form", 'status')

        form_data = await automation.fetch_initial_form()
        yield emit("  ✓ Form loaded (Status: 200)", 'log')
        yield emit(f"  ✓ Found {len(form_data['form_fields'])} form fields", 'log')

        if form_data['captcha_url']:
            yield emit(f"  ✓ CAPTCHA URL: {form_data['captcha_url'][:50]}...", 'log')
        yield emit("", 'log')

        # Step 2 & 3: Solve CAPTCHA and authenticate (with retry logic)
        max_captcha_attempts = 3
        captcha_attempt = 0
        result = None

        while captcha_attempt < max_captcha_attempts:
            captcha_attempt += 1

            # Solve CAPTCHA
            yield emit(
                f"[2/7] Solving CAPTCHA with Google Vision API (attempt {captcha_attempt}/{max_captcha_attempts})...",
                'log'
            )
            yield emit("Solving CAPTCHA", 'status')

            captcha_text = await automation.download_and_solve_captcha(
                form_data['captcha_url']
            )

            # Validate CAPTCHA format (should be exactly 5 digits)
            if not captcha_text.isdigit() or len(captcha_text) != 5:
                yield emit(
                    f"  ⚠ CAPTCHA format invalid: '{captcha_text}' (expected 5 digits)",
                    'log'
                )
                if captcha_attempt < max_captcha_attempts:
                    yield emit("  ↻ Retrying with fresh CAPTCHA...", 'log')
                    # Refetch form to get new CAPTCHA
                    form_data = await automation.fetch_initial_form()
                    continue
                else:
                    raise ValueError(
                        f"Failed to solve CAPTCHA after {max_captcha_attempts} attempts"
                    )

            yield emit(f"  ✓ CAPTCHA solved: {captcha_text}", 'log')
            yield emit("", 'log')

            # Submit authentication
            yield emit("[3/7] Submitting authentication...", 'log')
            yield emit("Authenticating", 'status')

            result = await automation.submit_form(
                form_action=form_data['form_action'],
                form_fields=form_data['form_fields'],
                account_number=settings.account_number,
                zip_code=settings.zip_code,
                last_name=settings.last_name,
                captcha_text=captcha_text,
                form_method=form_data['form_method']
            )

            # Check if CAPTCHA was rejected
            if "Please Enter Valid Captcha Text" in result['html']:
                yield emit(
                    f"  ✗ CAPTCHA rejected by server: '{captcha_text}'",
                    'log'
                )
                if captcha_attempt < max_captcha_attempts:
                    yield emit("  ↻ Retrying with fresh CAPTCHA...", 'log')
                    # Refetch form to get new CAPTCHA
                    form_data = await automation.fetch_initial_form()
                    continue
                else:
                    raise ValueError(
                        f"CAPTCHA validation failed after {max_captcha_attempts} attempts"
                    )

            # Success!
            yield emit(f"  ✓ Authentication submitted (Status: {result['status']})", 'log')

            # Debug: Show session info
            session_id = result.get('cookies', {}).get('JSESSIONID', 'N/A')
            yield emit(f"  ℹ Session ID: {session_id}", 'log')

            yield emit("", 'log')
            break

        # Ensure we got a valid result
        if result is None:
            raise ValueError("Failed to authenticate - no valid response received")

        if settings.dry_run:
            # Download test PDF from Wikipedia
            test_pdf_url = "https://upload.wikimedia.org/wikipedia/commons/d/d3/Test.pdf"
            temp_files = []

            try:
                yield emit("Downloading permit PDF...", 'log')
                response = await automation.client.get(test_pdf_url)
                response.raise_for_status()

                async for result in save_and_print_pdf(response.content, 'test', auto_print, automation, emit):
                    if isinstance(result, tuple):
                        temp_file, _ = result
                        temp_files.append(temp_file)
                    else:
                        yield result
            except Exception as e:
                yield emit(f"  ✗ Failed to download PDF: {e}", 'log')

            yield emit("=" * 60, 'log')
            yield emit("Workflow completed successfully!", 'log')
            permit_text = f"{num_permits} permit" if num_permits == 1 else f"{num_permits} permits"
            yield emit("Complete", 'status')
            yield emit(f"Generated {permit_text}", 'complete', files=temp_files)
            return

        # Step 4: Parse permit details form
        yield emit("[4/7] Parsing permit details form...", 'log')
        yield emit("Processing form", 'status')

        next_form = await automation.parse_next_form(result['html'])
        yield emit(f"  ✓ Found form action: {next_form['form_action']}", 'log')
        yield emit(f"  ✓ Found {len(next_form['form_fields'])} fields", 'log')

        # Debug: Show field names and TokenKey for troubleshooting
        field_names = [name for name, _ in next_form['form_fields']]
        yield emit(f"  ℹ Fields: {', '.join(field_names)}", 'log')

        # Extract and display TokenKey for debugging
        token_key = next((value['value'] for name, value in next_form['form_fields'] if name == 'TokenKey'), None)
        if token_key:
            yield emit(f"  ℹ TokenKey: {token_key}", 'log')

        yield emit("", 'log')

        # Step 5: Submit permit request details
        yield emit("[5/7] Submitting permit request...", 'log')
        yield emit("Submitting permit request", 'status')

        today = date.today()

        # Debug: Show what we're submitting
        yield emit(f"  ℹ Requesting {num_permits} permit(s) for {today.strftime('%m/%d/%Y')}", 'log')
        yield emit(f"  ℹ Email: {email}", 'log')

        permit_result = await automation.submit_dynamic_form(
            form_action=next_form['form_action'],
            form_fields=next_form['form_fields'],
            updates={
                'permitCount': str(num_permits),
                'permitMonth': str(today.month),
                'permitDay': str(today.day),
                'permitYear': str(today.year),
                'email': email,
                'emailConfirm': email
            },
            form_method=next_form['form_method']
        )
        yield emit(f"  ✓ Permit details submitted (Status: {permit_result['status']})", 'log')
        yield emit("", 'log')

        # Step 6: Parse confirmation form
        yield emit("[6/7] Processing confirmation...", 'log')
        yield emit("Confirming", 'status')

        confirm_form = await automation.parse_next_form(permit_result['html'])
        yield emit("  ✓ Confirmation form ready", 'log')

        # Debug: Show confirmation form details
        confirm_field_names = [name for name, _ in confirm_form['form_fields']]
        yield emit(f"  ℹ Confirmation fields: {', '.join(confirm_field_names)}", 'log')

        # Extract and display TokenKey for debugging
        confirm_token = next((value['value'] for name, value in confirm_form['form_fields'] if name == 'TokenKey'), None)
        if confirm_token:
            yield emit(f"  ℹ TokenKey: {confirm_token}", 'log')

        yield emit("", 'log')

        # Step 7: Final submission
        yield emit("[7/7] Final submission...", 'log')
        yield emit("Finalizing", 'status')

        final_result = await automation.submit_dynamic_form(
            form_action=confirm_form['form_action'],
            form_fields=confirm_form['form_fields'],
            updates={
                'requestType': 'submit',
                'submit': 'Submit'
            },
            form_method=confirm_form['form_method']
        )
        yield emit(f"  ✓ Final submission complete (Status: {final_result['status']})", 'log')
        yield emit("", 'log')

        # Download PDFs
        yield emit("Extracting PDF links...", 'log')

        soup = BeautifulSoup(final_result['html'], 'lxml')

        # Find JavaScript PDF links
        pdf_links = []
        javascript_links = soup.find_all('a', href=lambda x: x and 'javascript:' in x.lower())
        yield emit(f"  ℹ Found {len(javascript_links)} JavaScript link(s) to parse", 'log')

        for link in javascript_links:
            href = link.get('href', '')
            match = re.search(r"['\"]([^'\"]*(?:pdf|FileType=pdf)[^'\"]*)['\"]", href)
            if match:
                pdf_url = match.group(1)
                if not pdf_url.startswith('http'):
                    pdf_url = f"https://wmq.etimspayments.com{pdf_url}"
                pdf_links.append(pdf_url)
                yield emit(f"  ℹ PDF link: {pdf_url}", 'log')

        yield emit(f"  ✓ Found {len(pdf_links)} PDF link(s)", 'log')
        yield emit("", 'log')

        # Validate that permits were actually generated
        if len(pdf_links) == 0:
            yield emit("✗ No permit PDFs were generated!", 'log')
            yield emit("", 'log')
            yield emit("Analyzing response for errors...", 'log')

            # Check for common error indicators in the HTML response
            error_messages = []

            # Look for error text patterns
            if "error" in final_result['html'].lower():
                error_section = soup.find(text=re.compile(r'error', re.IGNORECASE))
                if error_section:
                    error_messages.append(f"Error found in response: {error_section.strip()}")

            # Look for validation messages
            if "please" in final_result['html'].lower() and "valid" in final_result['html'].lower():
                validation_text = soup.find(text=re.compile(r'please.*valid', re.IGNORECASE))
                if validation_text:
                    error_messages.append(f"Validation issue: {validation_text.strip()}")

            # Check for alert/warning divs
            for alert in soup.find_all(['div', 'span'], class_=re.compile(r'(alert|error|warning)', re.IGNORECASE)):
                if alert.get_text(strip=True):
                    error_messages.append(f"Alert: {alert.get_text(strip=True)}")

            if error_messages:
                for msg in error_messages:
                    yield emit(f"  • {msg}", 'log')
            else:
                yield emit("  • No specific error message found in response", 'log')

            yield emit("", 'log')
            yield emit("DEBUG: Response HTML snippet (first 500 chars):", 'log')
            html_snippet = final_result['html'][:500].replace('\n', ' ').replace('\r', '')
            yield emit(f"  {html_snippet}...", 'log')
            yield emit("", 'log')

            # Look for any form elements or text that might indicate what went wrong
            yield emit("DEBUG: Checking page structure...", 'log')

            # Check for forms (might be back at a previous step)
            forms = soup.find_all('form')
            if forms:
                yield emit(f"  • Found {len(forms)} form(s) on page", 'log')
                for idx, form in enumerate(forms[:2], 1):
                    form_action = form.get('action', 'N/A')
                    yield emit(f"    Form {idx}: action='{form_action}'", 'log')

            # Check for any text in the body
            body = soup.find('body')
            if body:
                body_text = body.get_text(strip=True)[:200]
                yield emit(f"  • Body text (first 200 chars): {body_text}", 'log')

            # Check page title
            title = soup.find('title')
            if title:
                yield emit(f"  • Page title: {title.get_text(strip=True)}", 'log')

            yield emit("", 'log')
            raise ValueError(
                "Permit generation failed: Final submission returned HTTP 200 but no PDF links were found. "
                "The form may have validation errors or the submission may not have been processed."
            )

        # Download and print PDF (contains all requested permits)
        pdf_url = pdf_links[0]
        temp_files = []

        yield emit("Downloading permit PDF...", 'log')
        yield emit("Downloading PDF", 'status')

        pdf_bytes = await automation.download_permit_pdf(pdf_url)

        print_success = False
        async for result in save_and_print_pdf(pdf_bytes, 1, auto_print, automation, emit):
            if isinstance(result, tuple):
                temp_file, print_success = result
                temp_files.append(temp_file)
            else:
                yield result

        yield emit("=" * 60, 'log')
        yield emit("Workflow completed successfully!", 'log')

        # Determine final status message
        permit_text = f"{num_permits} permit" if num_permits == 1 else f"{num_permits} permits"
        if auto_print:
            if print_success:
                final_message = f"Generated and printed {permit_text}"
            else:
                final_message = f"Generated {permit_text} but printing failed"
        else:
            final_message = f"Generated {permit_text}"
        yield emit(final_message, 'log')

        yield emit("=" * 60, 'log')
        yield emit("Complete!", 'status')
        yield emit(final_message, 'complete', files=temp_files)


@app.get("/stream")
async def stream_progress(request: Request, permits: int = 1, auto_print: str = "true"):
    """
    Server-Sent Events endpoint for streaming progress.
    """
    # Extract email from Cloudflare Access header if present
    user_email = request.headers.get("cf-access-authenticated-user-email")

    # Convert string to boolean
    auto_print_bool = auto_print.lower() == "true"

    async def event_generator():
        try:
            async for event in generate_permits_stream(permits, auto_print_bool, user_email):
                async for chunk in event:
                    yield chunk
                await asyncio.sleep(0.01)  # Small delay for smooth streaming
        except Exception as e:
            # Emit error as Server-Sent Event
            error_data = {'type': 'error', 'message': str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"
            # Also emit traceback to log
            log_data = {'type': 'log', 'message': traceback.format_exc()}
            yield f"data: {json.dumps(log_data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.get("/download/{filename}")
async def download_permit(filename: str):
    """
    Download a temporary permit PDF file.
    Files are automatically deleted after 10 minutes.
    """
    # Sanitize filename to prevent directory traversal
    safe_filename = Path(filename).name
    file_path = Path("/tmp") / safe_filename

    # Only allow files that start with 'permit_' for security
    if not safe_filename.startswith('permit_') or not safe_filename.endswith('.pdf'):
        return {"error": "Invalid filename"}

    if not file_path.exists():
        return {"error": "File not found or has expired"}

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=f"santa-monica-permit-{safe_filename}",
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "permit-automation"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1886, log_level="info")
