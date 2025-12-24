FROM debian:latest

# Install system dependencies including CUPS and curl for uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    cups \
    cups-client \
    cups-bsd \
    printer-driver-all \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY *.py ./
COPY .env.example ./

# Install Python and dependencies with uv (uv will download Python automatically)
RUN uv sync --frozen

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Environment variables
ENV PRINTER_IP=""
ENV PRINTER_NAME="AutoPrinter"
ENV PYTHONUNBUFFERED=1
ENV DRY_RUN="false"

# Expose web service and CUPS
EXPOSE 8000 631

# Use entrypoint script to start CUPS and run the app
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Default: run web service
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
