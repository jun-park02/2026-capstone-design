FROM python:3.11.14-slim
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# CMD은 docker-compose에서 지정

