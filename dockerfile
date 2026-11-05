# Math tutor Foundry hosted agent (Responses protocol).

FROM python:3.11-slim@sha256:064f01707f2fc8b06bae86bb43875266c6e41bac7994e77ec5dc623c4a4d0545

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false

# Copy requirements first for better layer caching
COPY requirements.lock.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --require-hashes -r requirements.lock.txt

# Create non-root user for security
RUN useradd -m -u 1000 appuser
COPY --chown=appuser:appuser main.py server_docs.py ./
COPY --chown=appuser:appuser agents/ ./agents/
COPY --chown=appuser:appuser operations/ ./operations/
COPY --chown=appuser:appuser tools/ ./tools/
USER appuser
ENV HOME=/home/appuser

# The Agent Server SDK listens on all interfaces on port 8088.
EXPOSE 8088

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://localhost:8088/readiness', timeout=5).close()"]

# Run the application
CMD ["python", "main.py"]
