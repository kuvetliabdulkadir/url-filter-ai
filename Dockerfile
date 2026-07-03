FROM python:3.12-slim

# guvenlik: root olmayan kullanici olustur
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# bagimliliklari kur (onbellek icin ayri katman)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# uygulama kodunu kopyala
COPY app/ ./app/
COPY static/ ./static/

# guvenlik: root degil appuser olarak calistir
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]