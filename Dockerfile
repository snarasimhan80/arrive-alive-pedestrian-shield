FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOSTED_DEMO=1 \
    DEMO_JOBS_DIR=/tmp/arrive-alive-jobs \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 user
WORKDIR /app

COPY requirements.txt requirements-hosted.txt ./
RUN pip install --no-cache-dir torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements-hosted.txt

COPY --chown=user:user . .

USER user
RUN python scripts/build_source.py --allow-unvalidated
EXPOSE 7860
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:7860", "--timeout", "120", "app:app"]
