# Cronoanalise - Demo -- imagem de producao do backend (que tambem
# serve o frontend estatico, ver backend/main.py).
#
# Mesma versao de Python do ambiente de desenvolvimento (`python --version`
# na maquina do projeto), para nao introduzir divergencia de comportamento
# entre local e container.
FROM python:3.14.7-slim

WORKDIR /app

# Dependencias Python primeiro (camada cacheada separadamente do codigo --
# so reinstala se requirements.txt mudar).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia so o que o backend LE em runtime (confirmado por busca em
# backend/):
#   backend/               -- o codigo da aplicacao
#   frontend/              -- servido estaticamente por StaticFiles (main.py)
#   dados/                 -- base oficial de atividades (backend/dados/base.py)
#
# Deliberadamente NAO copiado (nem pelo .dockerignore, nem aqui): venv/,
# tests/, scripts/, docs/, .git/, .claude/, README.md, CLAUDE.md, e
# principalmente as pastas de folha REAL que already apareceram soltas na
# raiz do projeto durante o desenvolvimento (fotos para testes/,
# PDF_Fotos_Teste/, calibracao/) -- COPY explicito por diretorio, em vez
# de `COPY . .` + .dockerignore, e a garantia de que nenhuma delas entra
# na imagem mesmo que o .dockerignore falhe em casar um nome com espaco.
COPY backend/ backend/
COPY frontend/ frontend/
COPY dados/ dados/

# O Render injeta $PORT em runtime e espera o container escutar nela;
# 8080 e so o valor de partida para rodar localmente sem definir nada.
ENV PORT=8080
EXPOSE 8080

# Forma shell (nao exec) de proposito: e a unica forma de expandir $PORT
# sem um script de entrypoint a parte. `exec` troca o shell pelo processo
# do uvicorn (PID 1 vira o uvicorn, nao um `sh` pendurado por cima) --
# necessario para o processo receber SIGTERM do Render diretamente e
# encerrar de forma graciosa, sem depender de terminal interativo.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
