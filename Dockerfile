FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render impose une variable d'environnement PORT
EXPOSE 10000
ENV PORT=10000

CMD ["python", "main.py"]
