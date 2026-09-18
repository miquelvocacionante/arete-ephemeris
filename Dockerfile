FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EPHE_PATH=/app/ephe

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY aspect_search.py ./
COPY cross_aspects.py ./
COPY engine_integrity.py ./
COPY progressions.py ./
COPY solar_return.py ./
COPY verify_swiss_real.py ./

COPY ephe ./ephe

# Release gate: never build an image that silently degrades to Moshier.
# Required files in /app/ephe:
#   sepl_18.se1, semo_18.se1, seas_18.se1
RUN EPHE_PATH=/app/ephe python verify_swiss_real.py

EXPOSE 8080

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 --access-logfile - --error-logfile - app:app"]
