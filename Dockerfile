FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg aria2

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "server:app", "--bind", "0.0.0.0:8080"]
