"""
FastAPI web service for Santa Monica parking permit automation.
"""

import asyncio
import json
import re
import traceback
from collections.abc import AsyncGenerator
from datetime import date

import uvicorn
from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from main import SantaMonicaPermitAutomation
from settings import settings

app = FastAPI(title="Santa Monica Permit Automation")

# HTML template inline (can move to separate file later)
HOME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Santa Monica Permit Request</title>
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 0;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            padding: 24px;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            width: 100%;
            max-width: 480px;
            margin: 16px;
        }
        h1 {
            color: #1976d2;
            margin: 0 0 8px 0;
            font-size: 28px;
            line-height: 1.2;
        }
        .subtitle {
            color: #666;
            margin-bottom: 32px;
            font-size: 16px;
        }
        .form-group {
            margin-bottom: 24px;
        }
        label {
            display: block;
            margin-bottom: 12px;
            font-weight: 600;
            color: #333;
            font-size: 18px;
        }
        input[type="number"] {
            width: 100%;
            padding: 16px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 20px;
            -webkit-appearance: none;
            appearance: none;
        }
        input[type="number"]:focus {
            outline: none;
            border-color: #1976d2;
        }
        .go-button {
            width: 100%;
            padding: 20px;
            background: #1976d2;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 22px;
            font-weight: bold;
            cursor: pointer;
            -webkit-tap-highlight-color: transparent;
            touch-action: manipulation;
        }
        .go-button:active {
            background: #0d47a1;
            transform: scale(0.98);
        }
        .info {
            background: #e3f2fd;
            padding: 16px;
            border-radius: 8px;
            margin-top: 24px;
            font-size: 15px;
            color: #1565c0;
            line-height: 1.6;
        }
        .info strong {
            display: inline-block;
            min-width: 90px;
        }
        .dry-run-badge {
            display: inline-block;
            background: #ff9800;
            color: white;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: bold;
            margin-top: 8px;
            vertical-align: middle;
        }
        @media (max-width: 480px) {
            .container {
                margin: 8px;
                padding: 20px;
            }
            h1 {
                font-size: 24px;
            }
            .dry-run-badge {
                display: block;
                margin-top: 8px;
                margin-left: 0;
                text-align: center;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>
            Santa Monica Permit Request
            {% if dry_run %}
            <span class="dry-run-badge">DRY-RUN MODE</span>
            {% endif %}
        </h1>
        <p class="subtitle">Request temporary parking permits</p>

        <form action="/generate" method="post" id="permitForm">
            <div class="form-group">
                <label for="permits">Number of Permits:</label>
                <input type="number" id="permits" name="permits" min="1" max="5" value="1" required>
            </div>

            <button type="submit" class="go-button">GO</button>
        </form>

        <div class="info">
            <strong>Account:</strong> {{ account_number }}<br>
            <strong>Name:</strong> {{ last_name }}<br>
            <strong>Email:</strong> <!--email_off-->{{ email }}<!--/email_off--><br>
            {% if dry_run %}
            <strong>Mode:</strong> Test mode - will not submit final request
            {% else %}
            <strong>Auto-Print:</strong> {{ auto_print }}
            {% endif %}
        </div>
    </div>

</body>
</html>
"""

PROGRESS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Generating Permits...</title>
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Mono', 'Courier New', monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            margin: 0;
            padding: 12px;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            background: #2d2d2d;
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            flex-shrink: 0;
        }
        h1 {
            margin: 0;
            color: #4ec9b0;
            font-size: 20px;
            line-height: 1.3;
        }
        .subtitle {
            color: #9cdcfe;
            margin-top: 6px;
            font-size: 14px;
        }
        #log {
            background: #1e1e1e;
            padding: 12px;
            border-radius: 8px;
            border: 2px solid #3e3e3e;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 13px;
            line-height: 1.5;
            overflow-y: auto;
            flex-grow: 1;
            -webkit-overflow-scrolling: touch;
        }
        .log-line {
            margin-bottom: 4px;
        }
        .step {
            color: #569cd6;
            font-weight: bold;
        }
        .success {
            color: #4ec9b0;
        }
        .error {
            color: #f48771;
        }
        .info {
            color: #9cdcfe;
        }
        .timestamp {
            color: #6a9955;
            margin-right: 8px;
            font-size: 11px;
        }
        .spinner {
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid #3e3e3e;
            border-top: 2px solid #4ec9b0;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 8px;
            vertical-align: middle;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .status-bar {
            background: #2d2d2d;
            padding: 14px 16px;
            margin-top: 12px;
            border-radius: 8px;
            font-size: 14px;
            flex-shrink: 0;
        }
        #status {
            color: #4ec9b0;
            font-weight: bold;
        }
        .back-button {
            display: inline-block;
            margin-top: 14px;
            padding: 14px 24px;
            background: #0e639c;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            -webkit-tap-highlight-color: transparent;
            touch-action: manipulation;
            font-size: 16px;
            font-weight: 600;
        }
        .back-button:active {
            background: #1177bb;
            transform: scale(0.98);
        }
        @media (max-width: 480px) {
            body {
                padding: 8px;
            }
            .header {
                padding: 12px;
            }
            h1 {
                font-size: 18px;
            }
            .subtitle {
                font-size: 13px;
            }
            #log {
                font-size: 12px;
                padding: 10px;
            }
            .timestamp {
                display: block;
                font-size: 10px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span class="spinner"></span>Generating Permits</h1>
        <div class="subtitle">Requesting {{ permits }} permit(s)...</div>
    </div>

    <div id="log"></div>

    <div class="status-bar">
        <span id="status">Connecting...</span>
    </div>

    <script>
        const log = document.getElementById('log');
        const status = document.getElementById('status');
        const eventSource = new EventSource('/stream?permits={{ permits }}');

        let lastMessageTime = Date.now();

        eventSource.onmessage = function(event) {
            lastMessageTime = Date.now();
            const data = JSON.parse(event.data);

            if (data.type === 'log') {
                const now = new Date();
                const timestamp = now.toTimeString().split(' ')[0];

                let className = 'log-line';
                if (data.message.includes('✓') || data.message.includes('Success')) {
                    className += ' success';
                } else if (data.message.includes('✗') || data.message.includes('Error')) {
                    className += ' error';
                } else if (data.message.includes('[') && data.message.includes(']')) {
                    className += ' step';
                } else {
                    className += ' info';
                }

                log.innerHTML += `<div class="${className}"><span class="timestamp">${timestamp}</span>${data.message}</div>`;
                log.scrollTop = log.scrollHeight;
            } else if (data.type === 'status') {
                status.textContent = data.message;
            } else if (data.type === 'complete') {
                status.textContent = '✓ Complete!';
                document.querySelector('.spinner').style.display = 'none';
                eventSource.close();

                // Add back button
                const statusBar = document.querySelector('.status-bar');
                statusBar.innerHTML += '<br><a href="/" class="back-button">← Back to Home</a>';
            } else if (data.type === 'error') {
                status.textContent = '✗ Error: ' + data.message;
                status.className = 'error';
                eventSource.close();
            }
        };

        eventSource.onerror = function() {
            if (Date.now() - lastMessageTime > 2000) {
                status.textContent = '✗ Connection lost';
                status.className = 'error';
                eventSource.close();
            }
        };

        // Keep connection alive check
        setInterval(() => {
            if (Date.now() - lastMessageTime > 30000) {
                status.textContent = '⚠ No updates for 30 seconds...';
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
    auto_print = settings.auto_print

    # Simple template rendering (we'll use jinja2 for proper template support)
    html = HOME_TEMPLATE
    html = html.replace('{{ account_number }}', str(account_number))
    html = html.replace('{{ last_name }}', str(last_name))
    html = html.replace('{{ email }}', str(email))
    html = html.replace('{{ auto_print }}', 'Yes' if auto_print else 'No')

    # Handle conditional dry_run badge
    if dry_run:
        html = html.replace('{% if dry_run %}', '')
        html = html.replace('{% endif %}', '')
        html = html.replace('{% else %}', '<!--')
        html = html.replace('{% if dry_run %}', '<!--')
    else:
        html = html.replace('{% if dry_run %}', '<!--')
        html = html.replace('{% else %}', '')
        html = html.replace('{% endif %}', '-->')

    return HTMLResponse(content=html)


@app.post("/generate", response_class=HTMLResponse)
async def generate_page(permits: int = Form(1)):
    """Progress page that streams permit generation."""
    html = PROGRESS_TEMPLATE.replace('{{ permits }}', str(permits))
    return HTMLResponse(content=html)


async def generate_permits_stream(
    num_permits: int, user_email: str | None = None
) -> AsyncGenerator[str]:
    """
    Generator that yields Server-Sent Events with progress updates.

    Args:
        num_permits: Number of permits to generate
        user_email: Override email (e.g. from Cloudflare Access), falls back to settings
    """

    async def emit(message: str, event_type: str = 'log'):
        """Emit a Server-Sent Event."""
        data = json.dumps({'type': event_type, 'message': message})
        yield f"data: {data}\n\n"

    try:
        # Use provided email or fall back to settings
        email = user_email or settings.email
        yield emit("=" * 60, 'log')
        if settings.dry_run:
            yield emit("DRY-RUN MODE - Test workflow without final submission", 'log')
        else:
            yield emit("Santa Monica Parking Permit Automation", 'log')
        yield emit("=" * 60, 'log')
        yield emit(f"Requesting {num_permits} permit(s)", 'log')
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
                yield emit("=" * 60, 'log')
                yield emit("DRY-RUN: Stopping before final submission", 'log')
                yield emit("", 'log')

                # Print test permit
                if settings.auto_print:
                    yield emit("[Test] Printing demo permit...", 'log')
                    yield emit("Printing demo", 'status')

                    # Download test PDF from Wikipedia
                    test_pdf_url = "https://upload.wikimedia.org/wikipedia/commons/d/d3/Test.pdf"

                    try:
                        yield emit("  • Downloading test PDF from Wikipedia...", 'log')
                        response = await automation.client.get(test_pdf_url)
                        response.raise_for_status()

                        test_pdf_bytes = response.content
                        yield emit(f"  ✓ Test PDF downloaded ({len(test_pdf_bytes)} bytes)", 'log')

                        print_success = await automation.print_pdf(
                            test_pdf_bytes, settings.printer_name
                        )

                        if print_success:
                            yield emit(
                                f"  ✓ Demo permit sent to printer: {settings.printer_name}", 'log'
                            )
                        else:
                            yield emit("  ✗ Failed to print demo permit", 'log')
                    except Exception as e:
                        yield emit(f"  ✗ Failed to download test PDF: {e}", 'log')

                yield emit("=" * 60, 'log')
                yield emit("Dry-run test completed successfully!", 'log')
                yield emit("Complete", 'status')
                yield emit("", 'complete')
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

            # Download and print PDFs
            for i, pdf_url in enumerate(pdf_links, 1):
                yield emit(f"Downloading permit {i}/{len(pdf_links)}...", 'log')
                yield emit(f"Downloading permit {i}", 'status')

                pdf_bytes = await automation.download_permit_pdf(pdf_url)
                yield emit(f"  ✓ Downloaded permit {i} ({len(pdf_bytes)} bytes)", 'log')

                if settings.auto_print:
                    yield emit(f"  📄 Printing permit {i} to {settings.printer_name}...", 'log')
                    print_success = await automation.print_pdf(pdf_bytes, settings.printer_name)

                    if print_success:
                        yield emit("  ✓ Print job submitted successfully", 'log')
                    else:
                        yield emit("  ✗ Print job failed", 'log')

                yield emit("", 'log')

            yield emit("=" * 60, 'log')
            yield emit("Workflow completed successfully!", 'log')
            yield emit(f"Generated {len(pdf_links)} permit(s)", 'log')
            yield emit("=" * 60, 'log')
            yield emit("Complete!", 'status')
            yield emit("", 'complete')

    except Exception as e:
        yield emit(f"Error: {e!s}", 'error')
        yield emit(traceback.format_exc(), 'log')


@app.get("/stream")
async def stream_progress(request: Request, permits: int = 1):
    """
    Server-Sent Events endpoint for streaming progress.
    """
    # Extract email from Cloudflare Access header if present
    user_email = request.headers.get("cf-access-authenticated-user-email")

    async def event_generator():
        async for event in generate_permits_stream(permits, user_email):
            async for chunk in event:
                yield chunk
            await asyncio.sleep(0.01)  # Small delay for smooth streaming

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "permit-automation"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1886, log_level="info")
