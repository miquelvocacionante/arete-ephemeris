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
COPY download_ephemeris.py ./
COPY verify_swiss_real.py ./

# Descarga reproducible desde el repositorio público oficial de Swiss
# y validación real del motor. Si cualquiera de las dos cosas falla,
# Railway no obtiene una imagen desplegable.
RUN python download_ephemeris.py \
    && EPHE_PATH=/app/ephe python verify_swiss_real.py

EXPOSE 8080

# Se vuelve a validar al arrancar: si Railway sobrescribe EPHE_PATH o el
# filesystem/runtime no coincide con la imagen validada, el servicio falla
# cerrado antes de aceptar tráfico.
CMD ["sh", "-c", "python verify_swiss_real.py && exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 --access-logfile - --error-logfile - app:app"]
