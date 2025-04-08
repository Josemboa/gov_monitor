# Use Python 3.10 as base image
FROM python:3.10-slim

# Set working directory in the container
WORKDIR /app

# Install required system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the SQLite database directory
COPY instance/ ./instance/

# Copy the application code
COPY . .

# Make sure the SQLite database is writable
RUN chmod -R 777 instance/

# Expose the port the app runs on
EXPOSE 8080

# Command to run the application
CMD exec gunicorn --bind :8080 --workers 1 --threads 8 --timeout 0 app:app