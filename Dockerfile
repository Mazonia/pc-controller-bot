# PC Remote Sentinel — Fleet Commander Bot Container
FROM python:3.11-slim

WORKDIR /app

# Install lightweight dependencies
COPY requirements-bot.txt .
RUN pip install --no-cache-dir -r requirements-bot.txt

# Copy bot code
COPY bot.py config.py fleet_relay.py ./

# Create data directories
RUN mkdir -p recordings downloads

CMD ["python", "bot.py"]
