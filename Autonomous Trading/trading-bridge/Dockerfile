FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Railway automatically detects the PORT environment variable
# If you run the dashboard, it needs to bind to $PORT.
# We modify run_dashboard.py dynamically at runtime to use $PORT if available.

# Note: In Railway, you can create two services from this same Dockerfile:
# Service 1 (The Trading Bot): Command = `python main.py --live` (or --demo)
# Service 2 (The Dashboard): Command = `python run_dashboard.py`
