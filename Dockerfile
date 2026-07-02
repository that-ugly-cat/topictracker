FROM python:3.12-slim

WORKDIR /app

# System deps for matplotlib/wordcloud
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libfreetype6-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model
RUN python -m spacy download en_core_web_md

COPY . .

# Persistent storage dirs
RUN mkdir -p data export static

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
