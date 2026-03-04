# 1. Use the official Playwright image that matches your requirements.txt version
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

# 2. Set environment variables for Render compatibility and memory efficiency
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=10000

# 3. Set the working directory
WORKDIR /app

# 4. Install Python dependencies first (for better build caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Install the Chromium browser binary
# This base image already contains the system dependencies (libs)
RUN playwright install chromium

# 6. Copy the application code
COPY main.py .

# 7. Create the storage directory for profile photos
RUN mkdir -p profile_photos

# 8. Expose the port Render expects
EXPOSE 10000

# 9. Start the application with a single worker to save RAM on the Free Tier
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000", "--workers", "1"]