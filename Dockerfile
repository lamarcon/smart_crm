FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup --system smartcrm \
    && adduser --system --ingroup smartcrm --home /app smartcrm

WORKDIR /app
COPY pyproject.toml /tmp/smartcrm-pyproject.toml
RUN python -c "import pathlib,subprocess,sys,tomllib; dependencies=tomllib.loads(pathlib.Path('/tmp/smartcrm-pyproject.toml').read_text())['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *dependencies])"

COPY --chown=smartcrm:smartcrm pyproject.toml /app/pyproject.toml
COPY --chown=smartcrm:smartcrm app/ /app/app/
COPY --chown=smartcrm:smartcrm alembic.ini /app/alembic.ini
COPY --chown=smartcrm:smartcrm migrations/ /app/migrations/
RUN python -m pip install --no-cache-dir --no-deps .

USER smartcrm
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=3 \
  CMD ["python", "-c", "import json,urllib.request; payload=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)); assert payload == {'status': 'ok', 'database': 'ok'}"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
