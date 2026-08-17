FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup --system smartcrm \
    && adduser --system --ingroup smartcrm --home /app smartcrm

WORKDIR /app
COPY --chown=smartcrm:smartcrm app/ /app/app/

USER smartcrm
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=3 \
  CMD ["python", "-c", "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2))['status'] == 'ok'"]

CMD ["python", "app/server.py", "--host", "0.0.0.0", "--port", "8000"]
