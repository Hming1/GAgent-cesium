FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# PIP_INDEX_URL can be overridden at build time when the default mirror is
# unreachable (e.g. --build-arg PIP_INDEX_URL=https://pypi.org/simple/).
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

COPY requirements.txt .

# Optional offline wheelhouse (git-ignored). Populate it when the build host has
# no working DNS for PyPI:
#   docker run --rm --dns <resolver> -v "$PWD/_wheels:/wheels" \
#     -v "$PWD/requirements.txt:/req.txt:ro" python:3.11-slim \
#     pip download --no-cache-dir -d /wheels -r /req.txt
COPY _wheels* ./_wheels/

RUN if [ -n "$(ls -A ./_wheels 2>/dev/null)" ]; then \
      echo "installing from offline wheelhouse"; \
      pip install --no-cache-dir --no-index --find-links ./_wheels -r requirements.txt; \
    else \
      echo "installing from ${PIP_INDEX_URL}"; \
      pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt; \
    fi \
 && rm -rf ./_wheels

COPY app ./app

RUN useradd --create-home --shell /usr/sbin/nologin sandbox
USER sandbox

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
