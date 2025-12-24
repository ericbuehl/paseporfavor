#!/bin/bash
set -e

echo "Configuring CUPS with debug logging..."

# Set maximum log level (debug2 = most verbose) before starting CUPS
# Edit cupsd.conf to set LogLevel
sed -i 's/^LogLevel .*/LogLevel debug2/' /etc/cups/cupsd.conf 2>/dev/null || echo "LogLevel debug2" >> /etc/cups/cupsd.conf

echo "Starting CUPS daemon..."
# Start CUPS in the background
cupsd

# Wait for CUPS to be ready
sleep 2

# Enable debug logging in CUPS (must be done after cupsd starts)
# This will log all print job operations, IPP requests, and backend activity
echo "Enabling CUPS debug logging..."
cupsctl --debug-logging

# Show CUPS log location
echo ""
echo "CUPS logs available at:"
echo "  - Error log: /var/log/cups/error_log"
echo "  - Access log: /var/log/cups/access_log"
echo "  - Page log: /var/log/cups/page_log"
echo ""

# Configure printer if PRINTER_IP is set
if [ -n "$PRINTER_IP" ]; then
    echo "Configuring printer at $PRINTER_IP..."

    # Add the printer using IPP protocol
    # Assumes the printer is accessible via IPP at the given IP
    lpadmin -p "$PRINTER_NAME" \
        -v "ipp://${PRINTER_IP}/ipp/print" \
        -E \
        -m everywhere

    # Set as default printer
    lpadmin -d "$PRINTER_NAME"

    # Enable the printer
    cupsenable "$PRINTER_NAME"
    cupsaccept "$PRINTER_NAME"

    echo "Printer '$PRINTER_NAME' configured successfully at $PRINTER_IP"

    # Test printer status
    lpstat -p "$PRINTER_NAME" || echo "Warning: Could not verify printer status"
else
    echo "Warning: PRINTER_IP not set. Printer will not be configured."
    echo "Set PRINTER_IP environment variable to enable automatic printing."
fi

echo "CUPS is ready. Starting application..."

# Tail CUPS error log in background to show print job activity
# This will appear in docker logs output
tail -F /var/log/cups/error_log 2>/dev/null | sed 's/^/[CUPS] /' &

# Execute the main command
exec "$@"
