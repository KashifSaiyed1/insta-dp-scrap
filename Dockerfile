# 1. Use the official Playwright Python image (it includes all dependencies)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# 2. Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

WORKDIR /app

# 3. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Install ONLY Chromium (Skip Firefox/Webkit to save space)
# Note: The dependencies are already in the base image!
RUN playwright install chromium

# 5. Copy your app code
COPY main.py .
RUN mkdir -p profile_photos

EXPOSE 10000

# 6. Start the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]