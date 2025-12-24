import asyncio
import base64
import json
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urljoin

import httpx
import jwt
from bs4 import BeautifulSoup

from settings import settings


class SantaMonicaPermitAutomation:
    """Automates Santa Monica temporary parking permit requests using httpx with asyncio."""

    BASE_URL = "https://wmq.etimspayments.com"
    FORM_URL = f"{BASE_URL}/pbw/include/santamonica/rppguestinput.jsp"
    VISION_API_URL = "https://vision.googleapis.com/v1/images:annotate"
    GOOGLE_OAUTH_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, google_credentials_file: str | None = None):
        """
        Initialize the automation client.

        Args:
            google_credentials_file: Path to Google service account JSON file.
                          If not provided, will use settings.google_credentials_file.
        """
        # AsyncClient with cookie persistence
        self.client: httpx.AsyncClient | None = None
        self.google_credentials_file: str = (
            google_credentials_file or settings.google_credentials_file
        )
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None

    async def __aenter__(self):
        """Initialize the async HTTP client with cookie jar."""
        self.client = httpx.AsyncClient(
            cookies=httpx.Cookies(),  # Persistent cookie store
            follow_redirects=True,
            timeout=30.0,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up the HTTP client."""
        if self.client:
            await self.client.aclose()

    async def fetch_initial_form(self) -> dict:
        """
        Fetch the initial form page and extract any hidden fields or tokens.
        Cookies from this request are automatically stored in the client.
        """
        response = await self.client.get(self.FORM_URL)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'lxml')

        # Extract form information
        form = soup.find('form')
        form_action = form.get('action') if form else None
        form_method = form.get('method', 'post').upper() if form else 'POST'

        # Extract all form inputs (including hidden fields)
        form_fields = {}
        if form:
            for input_tag in form.find_all(['input', 'select', 'textarea']):
                name = input_tag.get('name')
                value = input_tag.get('value', '')
                if name:
                    form_fields[name] = value

        # Find CAPTCHA image
        captcha_img = soup.find('img', {'id': 'captchaImg'}) or soup.find('img', src=lambda x: x and 'captcha' in x.lower())
        captcha_url = None
        if captcha_img:
            captcha_src = captcha_img.get('src')
            if captcha_src:
                captcha_url = urljoin(self.BASE_URL, captcha_src)

        return {
            'html': response.text,
            'cookies': dict(self.client.cookies),
            'status': response.status_code,
            'form_action': urljoin(self.BASE_URL, form_action) if form_action else None,
            'form_method': form_method,
            'form_fields': form_fields,
            'captcha_url': captcha_url
        }

    async def _get_access_token(self) -> str:
        """
        Get OAuth2 access token from service account credentials.
        Caches token until expiry.

        Returns:
            Valid access token

        Raises:
            ValueError: If credentials file is not configured or invalid
        """
        # Return cached token if still valid
        if (
            self._access_token
            and self._token_expiry
            and datetime.utcnow() < self._token_expiry - timedelta(minutes=5)
        ):
            return self._access_token

        if not self.google_credentials_file:
            raise ValueError("Google credentials file not configured")

        # Load service account credentials
        try:
            with open(self.google_credentials_file) as f:
                credentials = json.load(f)
        except FileNotFoundError as err:
            raise ValueError(
                f"Credentials file not found: {self.google_credentials_file}"
            ) from err
        except json.JSONDecodeError as err:
            raise ValueError(
                f"Invalid JSON in credentials file: {self.google_credentials_file}"
            ) from err

        # Extract required fields
        private_key = credentials.get('private_key')
        client_email = credentials.get('client_email')

        if not private_key or not client_email:
            raise ValueError("Credentials file missing 'private_key' or 'client_email'")

        # Create JWT assertion
        # Use current UTC timestamp
        now = int(time.time())
        expiry = now + 3600  # 1 hour from now

        jwt_payload = {
            'iss': client_email,
            'sub': client_email,
            'aud': self.GOOGLE_OAUTH_URL,
            'iat': now,
            'exp': expiry,
            'scope': 'https://www.googleapis.com/auth/cloud-vision'
        }

        # Sign JWT with private key
        jwt_token = jwt.encode(jwt_payload, private_key, algorithm='RS256')

        # Exchange JWT for access token
        async with httpx.AsyncClient() as oauth_client:
            response = await oauth_client.post(
                self.GOOGLE_OAUTH_URL,
                data={
                    'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                    'assertion': jwt_token
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30.0
            )

            # Better error handling
            if response.status_code != 200:
                error_detail = response.text
                raise ValueError(
                    f"Failed to obtain access token (HTTP {response.status_code}): {error_detail}"
                )

        token_data = response.json()

        if 'access_token' not in token_data:
            raise ValueError(f"Failed to obtain access token: {token_data}")

        # Cache the token
        self._access_token = token_data['access_token']
        expires_in = token_data.get('expires_in', 3600)
        self._token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

        return self._access_token

    async def solve_captcha_with_vision_api(self, image_content: bytes) -> str:
        """
        Use Google Cloud Vision API to perform OCR on CAPTCHA image.
        Uses direct REST API calls via httpx for full async support.
        Requires service account authentication.

        Args:
            image_content: Raw bytes of the CAPTCHA image

        Returns:
            Extracted text from the CAPTCHA

        Raises:
            ValueError: If credentials file is not configured
            httpx.HTTPError: If API request fails
        """
        if not self.google_credentials_file:
            raise ValueError(
                "Google credentials file not configured. Set GOOGLE_CREDENTIALS_FILE "
                "environment variable or pass google_credentials_file to constructor."
            )

        # Encode image to base64
        image_base64 = base64.b64encode(image_content).decode("utf-8")

        # Prepare Vision API request
        request_body = {
            "requests": [
                {
                    "image": {"content": image_base64},
                    "features": [{"type": "TEXT_DETECTION", "maxResults": 1}],
                }
            ]
        }

        # Make async request to Vision API with OAuth2
        async with httpx.AsyncClient() as api_client:
            # Get OAuth2 access token
            access_token = await self._get_access_token()
            url = self.VISION_API_URL
            headers = {"Authorization": f"Bearer {access_token}"}

            response = await api_client.post(
                url,
                json=request_body,
                headers=headers,
                timeout=30.0,
            )

            # Better error handling for Vision API
            if response.status_code != 200:
                error_detail = response.text
                raise ValueError(
                    f"Vision API error (HTTP {response.status_code}): {error_detail}\n"
                    f"Make sure:\n"
                    f"1. Vision API is enabled in Google Cloud Console\n"
                    f"2. Service account has 'Cloud Vision API User' role\n"
                    f"3. Billing is enabled for the project"
                )

        result = response.json()

        # Extract text from response
        if 'responses' in result and len(result['responses']) > 0:
            response_data = result['responses'][0]

            if 'textAnnotations' in response_data and len(response_data['textAnnotations']) > 0:
                # First annotation contains the full detected text
                detected_text = response_data['textAnnotations'][0]['description']
                # Clean up the text (remove whitespace, newlines)
                cleaned_text = detected_text.strip().replace('\n', '').replace(' ', '')
                return cleaned_text
            elif 'error' in response_data:
                error_msg = response_data['error'].get('message', 'Unknown error')
                raise ValueError(f"Vision API error: {error_msg}")
            else:
                raise ValueError("No text detected in CAPTCHA image")
        else:
            raise ValueError("Invalid response from Vision API")

    async def download_and_solve_captcha(self, captcha_url: str) -> str:
        """
        Download CAPTCHA and solve it using Google Vision API.
        Uses in-memory processing without saving temporary files.

        Args:
            captcha_url: URL of the CAPTCHA image

        Returns:
            Solved CAPTCHA text
        """
        # Download CAPTCHA (keep in memory only)
        response = await self.client.get(captcha_url)
        response.raise_for_status()
        image_content = response.content

        # Solve with Vision API
        captcha_text = await self.solve_captcha_with_vision_api(image_content)

        return captcha_text

    async def submit_form(
        self,
        form_action: str,
        form_fields: dict,
        account_number: str,
        zip_code: str,
        last_name: str,
        captcha_text: str,
        form_method: str = 'POST'
    ) -> dict:
        """
        Submit the permit request form with all required fields.
        Cookies are automatically sent with this request.

        Args:
            form_action: The form action URL from fetch_initial_form()
            form_fields: Hidden fields dict from fetch_initial_form()
            account_number: User's account number
            zip_code: Zip code (first 5 digits)
            last_name: Last name of account holder
            captcha_text: Solved CAPTCHA text
            form_method: HTTP method (GET or POST)
        """
        # Merge user data with hidden fields (using actual form field names)
        form_data = {
            **form_fields,  # Include all hidden fields
            'accountNo': account_number,
            'zip': zip_code[:5],
            'lastName': last_name,
            'captchaSText': captcha_text,
        }

        # Submit using the appropriate method
        if form_method.upper() == 'GET':
            response = await self.client.get(form_action, params=form_data)
        else:
            response = await self.client.post(form_action, data=form_data)

        response.raise_for_status()

        return {
            'html': response.text,
            'status': response.status_code,
            'url': str(response.url),
            'cookies': dict(self.client.cookies)
        }

    async def submit_permit_details(
        self,
        permit_quantity: int = 1,
        permit_date: str | None = None,
        email: str | None = None
    ) -> dict:
        """
        Submit permit details (quantity, date, email) after initial authentication.
        This is typically the second step in the form flow.

        Args:
            permit_quantity: Number of permits to request (default: 1)
            permit_date: Date for the permit (format: MM/DD/YYYY). Defaults to today.
            email: Email address for confirmation

        Returns:
            Dict with response HTML, status, and URL
        """
        # Default to today's date if not provided
        if not permit_date:
            today = date.today()
            permit_date = today.strftime('%m/%d/%Y')

        # Get email from settings if not provided
        if not email:
            email = settings.email

        # Parse the current page to find the form action and fields
        # This will depend on the actual form structure after authentication

        return {
            'permit_quantity': permit_quantity,
            'permit_date': permit_date,
            'email': email,
            'status': 'pending'
        }

    async def parse_next_form(self, html_content: str) -> dict:
        """
        Parse the HTML response to extract the next form's action and fields.

        Args:
            html_content: HTML content from previous response

        Returns:
            Dict containing form_action, form_method, and form_fields
        """
        soup = BeautifulSoup(html_content, 'lxml')

        # Find the main form
        form = soup.find('form')
        if not form:
            return {
                'form_action': None,
                'form_method': None,
                'form_fields': {},
                'has_form': False
            }

        form_action = form.get('action')
        form_method = form.get('method', 'post').upper()

        # Extract all form inputs
        form_fields = {}
        for input_tag in form.find_all(['input', 'select', 'textarea']):
            name = input_tag.get('name')
            value = input_tag.get('value', '')
            input_type = input_tag.get('type', 'text')

            if name:
                form_fields[name] = {
                    'value': value,
                    'type': input_type
                }

        return {
            'form_action': urljoin(self.BASE_URL, form_action) if form_action else None,
            'form_method': form_method,
            'form_fields': form_fields,
            'has_form': True,
            'html': html_content
        }

    async def submit_dynamic_form(
        self,
        form_action: str,
        form_fields: dict,
        updates: dict,
        form_method: str = 'POST'
    ) -> dict:
        """
        Submit a form with dynamic field updates.

        Args:
            form_action: The form action URL
            form_fields: Dict of form fields from parse_next_form()
            updates: Dict of field names to update with new values
            form_method: HTTP method (GET or POST)

        Returns:
            Dict with response HTML, status, URL, and cookies
        """
        # Build form data, using existing values and applying updates
        form_data = {}
        for field_name, field_info in form_fields.items():
            if field_name in updates:
                form_data[field_name] = updates[field_name]
            else:
                form_data[field_name] = field_info.get('value', '')

        # Submit using the appropriate method
        if form_method.upper() == 'GET':
            response = await self.client.get(form_action, params=form_data)
        else:
            response = await self.client.post(form_action, data=form_data)

        response.raise_for_status()

        return {
            'html': response.text,
            'status': response.status_code,
            'url': str(response.url),
            'cookies': dict(self.client.cookies)
        }

    async def download_permit_pdf(self, pdf_url: str) -> bytes:
        """
        Download the generated permit PDF.
        Cookies from previous requests are automatically included.

        Args:
            pdf_url: URL of the PDF to download

        Returns:
            PDF content as bytes
        """
        response = await self.client.get(pdf_url)
        response.raise_for_status()

        return response.content

    async def print_pdf(self, pdf_source: Path | bytes, printer_name: str | None = None) -> bool:
        """
        Print a PDF file using the system's CUPS printer.
        Automatically handles temporary file creation and cleanup for bytes input.

        Args:
            pdf_source: Either a Path to PDF file, or bytes of PDF content
            printer_name: Name of the printer. If None, uses default printer.

        Returns:
            True if print job was submitted successfully, False otherwise
        """
        # Get printer name from settings if not provided
        if not printer_name:
            printer_name = settings.printer_name

        try:
            # Handle bytes input with temporary file
            if isinstance(pdf_source, bytes):
                with NamedTemporaryFile(mode='wb', suffix='.pdf', delete=True) as tmp_file:
                    tmp_file.write(pdf_source)
                    tmp_file.flush()  # Ensure data is written to disk

                    # Build lpr command
                    cmd = ['lpr']
                    if printer_name:
                        cmd.extend(['-P', printer_name])
                    cmd.append(tmp_file.name)

                    # Submit print job (file automatically deleted after this block)
                    subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    return True
            else:
                # Handle Path input
                if not pdf_source.exists():
                    raise FileNotFoundError(f"PDF file not found: {pdf_source}")

                # Build lpr command
                cmd = ['lpr']
                if printer_name:
                    cmd.extend(['-P', printer_name])
                cmd.append(str(pdf_source))

                # Submit print job
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True
                )
                return True

        except subprocess.CalledProcessError as e:
            print(f"Print job failed: {e.stderr}")
            return False
        except Exception as e:
            print(f"Error printing PDF: {e}")
            return False


async def main():
    """Example usage of the permit automation with Google Vision OCR."""

    # Use async context manager to ensure proper cleanup
    async with SantaMonicaPermitAutomation() as automation:

        # Step 1: Fetch the initial form (cookies are stored automatically)
        print("Fetching initial form...")
        form_data = await automation.fetch_initial_form()
        print(f"Form loaded. Status: {form_data['status']}")
        print(f"Cookies stored: {list(form_data['cookies'].keys())}")
        print(f"Form action: {form_data['form_action']}")
        print(f"Form method: {form_data['form_method']}")
        print(f"Hidden fields: {form_data['form_fields']}")
        print(f"CAPTCHA URL: {form_data['captcha_url']}")

        # Step 2: Download and solve CAPTCHA with Google Vision API
        if form_data['captcha_url']:
            print("\nDownloading and solving CAPTCHA with Google Vision API...")
            try:
                captcha_text = await automation.download_and_solve_captcha(
                    form_data['captcha_url']
                )
                print(f"CAPTCHA solved: {captcha_text}")

                # Step 3: Submit the form (cookies automatically sent)
                # Uncomment to submit the form with solved CAPTCHA
                # result = await automation.submit_form(
                #     form_action=form_data['form_action'],
                #     form_fields=form_data['form_fields'],
                #     account_number="YOUR_ACCOUNT_NUMBER",
                #     zip_code="90401",
                #     last_name="YOUR_LAST_NAME",
                #     captcha_text=captcha_text,
                #     form_method=form_data['form_method']
                # )
                # print(f"\nForm submitted. Status: {result['status']}")
                # print(f"Redirected to: {result['url']}")

                # Step 4: Download permit PDF if URL is provided in response
                # You might need to parse result['html'] to find the PDF link
                # pdf_path = await automation.download_permit_pdf("https://...")
                # print(f"Permit saved to: {pdf_path}")

            except ValueError as e:
                print(f"Error: {e}")
                print("\nTo use Google Vision API, set your API key:")
                print("  export GOOGLE_API_KEY='your-api-key-here'")
                print("\nOr pass it to the constructor:")
                print("  SantaMonicaPermitAutomation(google_api_key='your-key')")


async def test_ocr_only():
    """Test OCR functionality on an existing CAPTCHA image."""
    captcha_path = Path("captcha.jpg")

    if not captcha_path.exists():
        print("No captcha.jpg found. Run main() first to download a CAPTCHA.")
        return

    async with SantaMonicaPermitAutomation() as automation:
        print(f"Reading CAPTCHA from: {captcha_path}")
        image_content = captcha_path.read_bytes()

        try:
            captcha_text = await automation.solve_captcha_with_vision_api(image_content)
            print(f"Solved CAPTCHA: {captcha_text}")
        except ValueError as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
