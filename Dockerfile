FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget curl unzip xvfb gnupg ca-certificates \
    fonts-liberation \
    libasound2 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
    libdrm2 libgbm1 libglib2.0-0 libgtk-3-0 \
    libnspr4 libnss3 libx11-6 libxcb1 libxcomposite1 \
    libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Install Chrome + driver
RUN seleniumbase install chromedriver

COPY . .

EXPOSE 5000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "5000"]