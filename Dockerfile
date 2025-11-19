# Usamos Python 3.11 estable
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Variables por defecto (puedes ajustar)
ENV FLASK_ENV=production

# Comando de arranque: gunicorn apuntando a app:app (tu create_app ya crea app)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]
