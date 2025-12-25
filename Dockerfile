FROM debian:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    cups \
    cups-client \
    cups-bsd \
    printer-driver-all \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

COPY static/ ./static/

COPY *.py ./

ENV PYTHONUNBUFFERED=1

EXPOSE 1886

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "1886"]
