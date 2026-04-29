FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY clawfs ./clawfs
RUN pip install --no-cache-dir -e .

ENV CLAWFS_ROOT=/data
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "clawfs.api:app", "--host", "0.0.0.0", "--port", "8000"]
