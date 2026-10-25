# The upstream binary is an internal protocol service, never a published Web UI.
ARG YYB_IMAGE=ghcr.io/525815266/yyb-go-enhanced@sha256:4508ad732ad8935babe67178269923d64da404f9dbbd5fccde8b9bf3736a4513
FROM ${YYB_IMAGE} AS wechat
FROM python:3.14-slim-trixie
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy \
    PATH="/app/goodnight/.venv/bin:$PATH" \
    DATA_DIR=/app/data STATIC_DIR=/usr/share/nginx/html
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends nginx supervisor tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
COPY login/pyproject.toml login/uv.lock /app/login/
COPY goodnight/pyproject.toml goodnight/uv.lock /app/goodnight/
# Each package has its own uv lock and environment; no Node or npm build in Docker.
RUN uv sync --project /app/login --frozen --no-dev --no-cache --no-install-project \
    && uv sync --project /app/goodnight --frozen --no-dev --no-cache --no-install-project --no-install-package uestc-login \
    && rm -rf /var/lib/apt/lists/*
COPY login/uestc_login /app/login/uestc_login
COPY goodnight/goodnight /app/goodnight/goodnight
RUN uv sync --project /app/login --frozen --no-dev --no-cache \
    && uv sync --project /app/goodnight --frozen --no-dev --no-cache
COPY --from=wechat /app/yyb-go /usr/local/bin/yyb-go
RUN useradd --create-home --uid 10001 goodnight \
    && mkdir -p /app/data && chown goodnight:goodnight /app/data
# Build the frontend in app/ before using compose.local.yaml or CI image builds.
COPY app/build/client/ /usr/share/nginx/html/
RUN test -f /usr/share/nginx/html/index.html
COPY LICENSE THIRD_PARTY.md ./
COPY nginx.conf /etc/nginx/nginx.conf
COPY supervisord.conf /app/supervisord.conf
COPY nginx_entrypoint.sh /usr/local/bin/nginx_entrypoint.sh
RUN chmod +x /usr/local/bin/nginx_entrypoint.sh && nginx -t
STOPSIGNAL SIGTERM
EXPOSE 80
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1/api/health', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/nginx_entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/app/supervisord.conf"]
