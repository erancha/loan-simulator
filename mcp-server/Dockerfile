# syntax=docker/dockerfile:1
FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --system --no-create-home --shell /usr/sbin/nologin engine
# A new named volume copies the ownership of the directory it mounts over, so the engine can write.
RUN mkdir /data && chown engine /data
WORKDIR /app
# The pinned lockfile installs first so source edits reuse the dependency layer; it is mounted, not
# copied, so it never lands in the image.
RUN --mount=type=bind,source=mcp-server/requirements.txt,target=/tmp/requirements.txt \
    --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt
COPY mcp-server/pyproject.toml /build/
COPY mcp-server/src /build/src
RUN pip install --no-cache-dir --no-deps /build && rm -rf /build
USER engine
CMD ["python", "-m", "loan_engine"]
