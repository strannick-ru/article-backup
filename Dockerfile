FROM python:3.12-slim

WORKDIR /app

# Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY backup.py .
COPY src/ src/

ENTRYPOINT ["python", "backup.py"]
