FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl espeak-ng libespeak-ng1 ffmpeg \
        libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[desktop]" \
    && python -m spacy download en_core_web_sm \
    && python -m spacy download en_core_web_md

COPY . .

EXPOSE 8000

CMD ["sh", "entrypoint.sh"]
