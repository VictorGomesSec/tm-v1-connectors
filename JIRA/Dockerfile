# Dockerfile para tm-v1-connectors/JIRA
FROM python:3.11-slim

# evitar prompts e mensagens extras durante install
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# instalar dependências do sistema necessárias
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# copie arquivos de dependências primeiro (cache de camada)
COPY requirements.txt requirements.txt

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# copie o código
COPY . .

# criar usuário não-root para rodar a app
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app

USER appuser

# expõe nada por padrão (se sua app precisa expor porta, adicione EXPOSE <port>)
# EXPOSE 8080

# comando padrão (usamos -u para texto não armazenado em buffer)
CMD ["python", "-u", "app.py"]
