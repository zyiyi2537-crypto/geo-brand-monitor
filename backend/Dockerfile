FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml poetry.lock* /app/
RUN pip install --no-cache-dir poetry && poetry install --no-root

# Copy application code
COPY . /app

# Install the package
RUN poetry install

# Expose port
EXPOSE 8070

# Command to run the application
CMD ["poetry", "run", "uvicorn", "geo.main:app", "--host", "0.0.0.0", "--port", "8070"]
