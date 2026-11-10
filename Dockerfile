FROM python:3.12-slim

# 国内网络优先走清华镜像；可通过 build-arg 覆盖。
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY pyproject.toml ./
RUN python -c 'import subprocess, sys, tomllib; config = tomllib.load(open("pyproject.toml", "rb")); requirements = [*config["build-system"]["requires"], *config["project"]["dependencies"]]; subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", *requirements])'

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps --no-build-isolation .

EXPOSE 8000
CMD ["uvicorn", "invest_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
