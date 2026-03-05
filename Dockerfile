FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app.py .

# Copy Swiss Ephemeris data files (needed for asteroids like Chiron)
# Keep at least one file in the folder (e.g. .gitkeep) so Docker COPY doesn't fail.
COPY ephe ./ephe

# Expose port
EXPOSE 8080

# Run with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "app:app"]
