# syntax=docker/dockerfile:1
# The laya System-1 decision sidecar. Heavy (torch + HF checkpoints) — built only under the `laya`
# compose profile. HF_HOME points at a mounted volume so checkpoints survive restarts.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=9000 HF_HOME=/models
WORKDIR /app
COPY laya_service/app.py ./app.py
# laya pulls torch/transformers/huggingface_hub. torch comes from regular PyPI (the pytorch CPU index
# is proxy-rewritten in this environment → hash mismatch). ponytail: this pulls torch's default linux
# wheel (CUDA libs bundled, unused on CPU, bigger image) — the tradeoff for a path that installs here.
RUN pip install "laya" "fastapi>=0.110" "uvicorn[standard]>=0.30" "pydantic>=2"
EXPOSE 9000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
