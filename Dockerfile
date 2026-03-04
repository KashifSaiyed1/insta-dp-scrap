# 1. Use a standard slim Python image (much smaller than Playwright)
FROM python:3.11-slim

# 2. Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=10000

WORKDIR /app

# 3. Install the tiny requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the "Direct API" main.py
COPY main.py .

# 5. Render uses the $PORT env var
EXPOSE 10000

# 6. Start the server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]