FROM python:3.12-slim

# OCI (täytetään CI:ssä build-argseilla; paikallinen build voi jättää tyhjiksi)
ARG GIT_REVISION=""
ARG IMAGE_VERSION=""
ARG SOURCE_URL=""
ARG IMAGE_TITLE_SUFFIX="CPU"

LABEL org.opencontainers.image.title="datapankki-mcp (${IMAGE_TITLE_SUFFIX})"
LABEL org.opencontainers.image.description="ZT-RAG: EPUB/PDF-tietopankki, MCP (zt_*) ja zt_cli — PyTorch CPU."
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.version="${IMAGE_VERSION}"
LABEL org.opencontainers.image.revision="${GIT_REVISION}"
LABEL org.opencontainers.image.source="${SOURCE_URL}"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch (pieni image; toimii AMD-koneella ilman ROCm-kikkailua)
COPY requirements.txt requirements-nli.txt .
RUN pip install --no-cache-dir "torch>=2.2.0" --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-nli.txt

COPY devworkflow /app/devworkflow/

ENV PYTHONPATH=/app
ENV ZT_DATA_DIR=/data

RUN mkdir -p /data /tmp/devworkflow

# ZT-RAG MCP (oletus). DevWorkflow: ENTRYPOINT ["python", "-m", "devworkflow.mcp_server"]
ENTRYPOINT ["python", "-m", "devworkflow.zt_mcp_server"]
