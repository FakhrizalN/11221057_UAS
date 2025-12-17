FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -r -s /bin/bash appuser && chown -R appuser:appuser /app

# Copy requirements first for better caching
COPY --chown=appuser:appuser requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=appuser:appuser app/ ./app/

# Switch to non-root user
USER appuser

# Run the publisher
CMD ["python", "-m", "app.main"]
