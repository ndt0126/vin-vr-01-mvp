# VR-01 MVP: Inspection API + lifecycle controller + cong cu khoi tao lab.
# Build context = thu muc mvp/.  Pin digest cua base image trong .env (PYTHON_IMAGE) truoc khi ban giao.
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY packages packages
COPY tools tools
COPY tests tests
COPY docs docs
RUN useradd --uid 10001 --create-home vr01 && mkdir -p /run-data && chown vr01 /run-data
USER 10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
EXPOSE 8443 9443
CMD ["python", "backend/inspection_api.py", "--help"]
