# Use Python 3.11 slim image for multi-platform support
FROM python:3.11-slim

# Build arguments to ensure unique image IDs
ARG BUILD_TIMESTAMP
ARG BUILD_ID  
ARG GIT_HASH

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY config.py .
COPY config.json .
COPY logger.py .
COPY src/ ./src/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Set build info as environment variables (ensures unique layer)
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
ENV BUILD_ID=${BUILD_ID}
ENV GIT_HASH=${GIT_HASH}

# Add build info to image (creates unique layer every time)
RUN echo "Build Info:" > /app/build_info.txt && \
    echo "Timestamp: ${BUILD_TIMESTAMP}" >> /app/build_info.txt && \
    echo "Build ID: ${BUILD_ID}" >> /app/build_info.txt && \
    echo "Git Hash: ${GIT_HASH}" >> /app/build_info.txt && \
    echo "Built on: $(date)" >> /app/build_info.txt

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import pymongo; print('Health check passed')" || exit 1

# Default command - can be overridden with docker run arguments
CMD ["sh", "-c", "python main.py"]

