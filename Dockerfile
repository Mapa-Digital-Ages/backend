# Use Python 3.12 slim image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application source code
COPY src/ ./src/

# Set environment variable for Python path
ENV PYTHONPATH=/app/src

# Expose FastAPI port
EXPOSE 8000

# Run the application
CMD ["uv", "run", "uvicorn", "md_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
