FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PDF_EDITOR_TMP=/tmp/pdf-signature-editor

RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 app && useradd -u 10001 -g app -d /app app

WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY pdf_editor ./pdf_editor
RUN mkdir -p /tmp/pdf-signature-editor && chown app:app /tmp/pdf-signature-editor

USER app
EXPOSE 8057
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8057/health', timeout=3)" || exit 1
CMD ["gunicorn", "--bind", "0.0.0.0:8057", "--workers", "2", "--threads", "2", "--timeout", "120", "pdf_editor.web:app"]
