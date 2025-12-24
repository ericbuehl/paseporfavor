"""
FastAPI web service for Santa Monica parking permit automation.
"""

import asyncio
import json
import os
import re
import traceback
from datetime import datetime, date
from typing import AsyncGenerator

from bs4 import BeautifulSoup
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from main import SantaMonicaPermitAutomation

app = FastAPI(title="Santa Monica Permit Automation")

# HTML template inline (can move to separate file later)
HOME_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Santa Monica Permit Request</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #1976d2;
            margin-bottom: 10px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
            color: #333;
        }
        input[type="number"] {
            width: 100%;
            padding: 10px;
            border: 2px solid #ddd;
            border-radius: 4px;
            font-size: 16px;
            box-sizing: border-box;
        }
        input[type="number"]:focus {
            outline: none;
            border-color: #1976d2;
        }
        .go-button {
            width: 100%;
            padding: 15px;
            background: #1976d2;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 18px;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.3s;
        }
        .go-button:hover {
            background: #1565c0;
        }
        .go-button:active {
            background: #0d47a1;
        }
        .info {
            background: #e3f2fd;
            padding: 15px;
            border-radius: 4px;
            margin-top: 20px;
            font-size: 14px;
            color: #1565c0;
        }
        .dry-run-badge {
            display: inline-block;
            background: #ff9800;
            color: white;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            margin-left: 10px;
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
            <strong>Email:</strong> {{ email }}<br>
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
    <title>Generating Permits...</title>
    <style>
        body {
            font-family: 'Courier New', monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            margin: 0;
            padding: 20px;
        }
        .header {
            background: #2d2d2d;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        }
        h1 {
            margin: 0;
            color: #4ec9b0;
            font-size: 24px;
        }
        .subtitle {
            color: #9cdcfe;
            margin-top: 5px;
        }
        #log {
            background: #1e1e1e;
            padding: 20px;
            border-radius: 8px;
            border: 2px solid #3e3e3e;
            min-height: 400px;
            white-space: pre-wrap;
            font-size: 14px;
            line-height: 1.6;
        }
        .log-line {
            margin-bottom: 5px;
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
            margin-right: 10px;
        }
        .spinner {
            display: inline-block;
            width: 12px;
            height: 12px;
            border: 2px solid #3e3e3e;
            border-top: 2px solid #4ec9b0;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .status-bar {
            background: #2d2d2d;
            padding: 15px 20px;
            margin-top: 20px;
            border-radius: 8px;
            font-size: 14px;
        }
        #status {
            color: #4ec9b0;
            font-weight: bold;
        }
        .back-button {
            display: inline-block;
            margin-top: 20px;
            padding: 10px 20px;
            background: #0e639c;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            transition: background 0.3s;
        }
        .back-button:hover {
            background: #1177bb;
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
async def home():
    """Home page with permit request form."""
    dry_run = os.getenv('DRY_RUN', 'false').lower() in ('true', '1', 'yes')
    account_number = os.getenv('ACCOUNT_NUMBER', 'Not configured')
    last_name = os.getenv('LAST_NAME', 'Not configured')
    email = os.getenv('EMAIL', 'Not configured')
    auto_print = os.getenv('AUTO_PRINT', 'true').lower() in ('true', '1', 'yes')

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


async def generate_permits_stream(num_permits: int) -> AsyncGenerator[str, None]:
    """
    Generator that yields Server-Sent Events with progress updates.
    """

    async def emit(message: str, event_type: str = 'log'):
        """Emit a Server-Sent Event."""
        data = json.dumps({'type': event_type, 'message': message})
        yield f"data: {data}\n\n"

    try:
        # Configuration
        DRY_RUN = os.getenv('DRY_RUN', 'false').lower() in ('true', '1', 'yes')
        AUTO_PRINT = os.getenv('AUTO_PRINT', 'true').lower() in ('true', '1', 'yes')
        PRINTER_NAME = os.getenv('PRINTER_NAME', 'AutoPrinter')

        ACCOUNT_NUMBER = os.getenv('ACCOUNT_NUMBER')
        ZIP_CODE = os.getenv('ZIP_CODE', '90401')
        LAST_NAME = os.getenv('LAST_NAME')
        EMAIL = os.getenv('EMAIL')

        yield emit("=" * 60, 'log')
        if DRY_RUN:
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
            yield emit(f"  ✓ Form loaded (Status: 200)", 'log')
            yield emit(f"  ✓ Found {len(form_data['form_fields'])} form fields", 'log')

            if form_data['captcha_url']:
                yield emit(f"  ✓ CAPTCHA URL: {form_data['captcha_url'][:50]}...", 'log')
            yield emit("", 'log')

            # Step 2: Solve CAPTCHA
            yield emit("[2/7] Solving CAPTCHA with Google Vision API...", 'log')
            yield emit("Solving CAPTCHA", 'status')

            captcha_text = await automation.download_and_solve_captcha(
                form_data['captcha_url']
            )
            yield emit(f"  ✓ CAPTCHA solved: {captcha_text}", 'log')
            yield emit("", 'log')

            # Step 3: Submit authentication
            yield emit("[3/7] Submitting authentication...", 'log')
            yield emit("Authenticating", 'status')

            result = await automation.submit_form(
                form_action=form_data['form_action'],
                form_fields=form_data['form_fields'],
                account_number=ACCOUNT_NUMBER,
                zip_code=ZIP_CODE,
                last_name=LAST_NAME,
                captcha_text=captcha_text,
                form_method=form_data['form_method']
            )
            yield emit(f"  ✓ Authentication submitted (Status: {result['status']})", 'log')
            yield emit("", 'log')

            if DRY_RUN:
                yield emit("=" * 60, 'log')
                yield emit("DRY-RUN: Stopping before final submission", 'log')
                yield emit("", 'log')

                # Print test permit
                if AUTO_PRINT:
                    yield emit("[Test] Printing demo permit...", 'log')
                    yield emit("Printing demo", 'status')

                    # Download test PDF from Wikipedia
                    test_pdf_url = "https://upload.wikimedia.org/wikipedia/commons/d/d3/Test.pdf"

                    try:
                        yield emit(f"  • Downloading test PDF from Wikipedia...", 'log')
                        response = await automation.client.get(test_pdf_url)
                        response.raise_for_status()

                        test_pdf_bytes = response.content
                        yield emit(f"  ✓ Test PDF downloaded ({len(test_pdf_bytes)} bytes)", 'log')

                        print_success = await automation.print_pdf(test_pdf_bytes, PRINTER_NAME)

                        if print_success:
                            yield emit(f"  ✓ Demo permit sent to printer: {PRINTER_NAME}", 'log')
                        else:
                            yield emit(f"  ✗ Failed to print demo permit", 'log')
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
            yield emit("", 'log')

            # Step 5: Submit permit request details
            yield emit("[5/7] Submitting permit request...", 'log')
            yield emit("Submitting permit request", 'status')

            today = date.today().strftime('%m/%d/%Y')

            permit_result = await automation.submit_dynamic_form(
                form_action=next_form['form_action'],
                form_fields=next_form['form_fields'],
                updates={
                    'quantity': str(num_permits),
                    'date': today,
                    'email': EMAIL
                },
                form_method=next_form['form_method']
            )
            yield emit(f"  ✓ Permit details submitted (Status: {permit_result['status']})", 'log')
            yield emit("", 'log')

            # Step 6: Parse confirmation form
            yield emit("[6/7] Processing confirmation...", 'log')
            yield emit("Confirming", 'status')

            confirm_form = await automation.parse_next_form(permit_result['html'])
            yield emit(f"  ✓ Confirmation form ready", 'log')
            yield emit("", 'log')

            # Step 7: Final submission
            yield emit("[7/7] Final submission...", 'log')
            yield emit("Finalizing", 'status')

            final_result = await automation.submit_dynamic_form(
                form_action=confirm_form['form_action'],
                form_fields=confirm_form['form_fields'],
                updates={},
                form_method=confirm_form['form_method']
            )
            yield emit(f"  ✓ Final submission complete (Status: {final_result['status']})", 'log')
            yield emit("", 'log')

            # Download PDFs
            yield emit("Extracting PDF links...", 'log')

            soup = BeautifulSoup(final_result['html'], 'lxml')

            # Find JavaScript PDF links
            pdf_links = []
            for link in soup.find_all('a', href=lambda x: x and 'javascript:' in x.lower()):
                href = link.get('href', '')
                match = re.search(r"['\"]([^'\"]*(?:pdf|FileType=pdf)[^'\"]*)['\"]", href)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith('http'):
                        pdf_url = f"https://wmq.etimspayments.com{pdf_url}"
                    pdf_links.append(pdf_url)

            yield emit(f"  ✓ Found {len(pdf_links)} PDF link(s)", 'log')
            yield emit("", 'log')

            # Download and print PDFs
            for i, pdf_url in enumerate(pdf_links, 1):
                yield emit(f"Downloading permit {i}/{len(pdf_links)}...", 'log')
                yield emit(f"Downloading permit {i}", 'status')

                pdf_bytes = await automation.download_permit_pdf(pdf_url)
                yield emit(f"  ✓ Downloaded permit {i} ({len(pdf_bytes)} bytes)", 'log')

                if AUTO_PRINT:
                    yield emit(f"  📄 Printing permit {i} to {PRINTER_NAME}...", 'log')
                    print_success = await automation.print_pdf(pdf_bytes, PRINTER_NAME)

                    if print_success:
                        yield emit(f"  ✓ Print job submitted successfully", 'log')
                    else:
                        yield emit(f"  ✗ Print job failed", 'log')

                yield emit("", 'log')

            yield emit("=" * 60, 'log')
            yield emit("Workflow completed successfully!", 'log')
            yield emit(f"Generated {len(pdf_links)} permit(s)", 'log')
            yield emit("=" * 60, 'log')
            yield emit("Complete!", 'status')
            yield emit("", 'complete')

    except Exception as e:
        yield emit(f"Error: {str(e)}", 'error')
        yield emit(traceback.format_exc(), 'log')


@app.get("/stream")
async def stream_progress(permits: int = 1):
    """
    Server-Sent Events endpoint for streaming progress.
    """
    async def event_generator():
        async for event in generate_permits_stream(permits):
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
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
