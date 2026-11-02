"""
Backend do apoio a cronoanalise.

Um servidor so para tudo: login, health check, a API do chatbot e o
frontend (PWA) estatico. O frontend nao precisa de build, e assim o celular
acessa tudo pelo mesmo endereco, sem CORS.

Rotas /api/*: busca de atividades (`POST /api/atividades/buscar`) e a base
inteira para a busca offline do celular (`GET /api/atividades`). A analise
de PDF da folha foi removida em 22/09/2026 (ver CLAUDE.md). A chave de API
do LLM fica sempre deste lado, nunca no frontend.

Uso:
    venv\\Scripts\\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""

import hashlib
import html
import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.acesso import (
    NOME_DO_COOKIE,
    VALIDADE_COOKIE_S,
    consultores_permitidos,
    contador_padrao,
    criar_cookie,
    senha_confere,
    validar_cookie,
)
from backend.busca import BuscadorAtividades, ResultadoBusca, criar_buscador


# Sem isto, o nível efetivo do logger raiz fica em WARNING (o "handler de
# última instância" do Python) e todo `logger.info(...)` do projeto --
# login, consumo de tokens do LLM (`busca/llm_anthropic.py`)
# -- desaparece em produção (Render só vê o que o uvicorn escreve por
# conta própria). Achado na auditoria de fechamento do MVP (21/09/2026,
# BLOCO 1): nenhum módulo chamava `logging.basicConfig`. Nível por
# `LOG_LEVEL` (padrão INFO) para poder subir para DEBUG/baixar para
# WARNING sem redeploy de código.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
FRONTEND = RAIZ / "frontend"

# Sem /docs nem /openapi.json: ninguem usa a documentacao interativa em
# campo, e ela so descreveria a API (auditoria de seguranca, 23/09/2026).
app = FastAPI(
    title="Cronoanalise - Demo",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Rotas acessíveis sem sessão. Tudo o mais (API e frontend estático,
# montado em "/" no fim do arquivo) exige cookie válido — ver
# `exigir_login` abaixo e `backend/acesso.py` para o porquê (BLOCO 3 do
# plano de fechamento do MVP: com billing ativo, uma rota aberta pode
# gerar fatura, não só esgotar cota).
# `/sw.js`: o navegador busca o service worker para atualizá-lo, e ele não
# tem dado nenhum (só a lista de arquivos do app).
ROTAS_PUBLICAS = {"/health", "/login", "/sw.js"}


def _acesso_aberto() -> bool:
    """`ACESSO_ABERTO=1` dispensa o login (demo pública, sem dados reais).
    Só faz sentido SEM `ANTHROPIC_API_KEY`: com a chave, qualquer visitante
    consumiria o crédito (as cotas de LLM continuam valendo, mas todos
    contam como um único "Visitante")."""
    return os.environ.get("ACESSO_ABERTO", "").strip() == "1"


@app.middleware("http")
async def exigir_login(request: Request, call_next):
    if _acesso_aberto():
        if request.url.path == "/login":
            return RedirectResponse(url="/")
        request.state.consultor = "Visitante"
        request.state.sessao_id = "visitante"
        return await call_next(request)

    if request.url.path in ROTAS_PUBLICAS:
        return await call_next(request)

    sessao = validar_cookie(request.cookies.get(NOME_DO_COOKIE))
    # Login antigo com nome digitado à mão (antes da lista da equipe): vale
    # como sem sessão — a pessoa escolhe o nome na lista uma vez, e a cota
    # e a auditoria passam a usar o nome padronizado.
    equipe = consultores_permitidos()
    if sessao is not None and equipe and sessao.nome not in equipe:
        sessao = None
    if sessao is None:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "login necessário"}, status_code=401)
        return RedirectResponse(url="/login")

    request.state.consultor = sessao.nome
    request.state.sessao_id = sessao.sessao_id
    return await call_next(request)


# Registrado depois de `exigir_login`, então roda por fora dele e marca
# também o redirect/login. Sem cabeçalho, o navegador escolhia sozinho
# por quanto tempo usar o JS guardado — o app na Tela de Início do iPhone
# seguia com a versão antiga depois do deploy (23/09/2026). "no-cache"
# deixa guardar, mas obriga a conferir o ETag antes (304 se nada mudou).
# Cabeçalhos de segurança (auditoria, 23/09/2026). CSP: só recursos do
# próprio endereço; 'unsafe-inline' em style-src por causa do <style> do
# login.html (não há script inline em nenhuma página).
CABECALHOS_DE_SEGURANCA = {
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000",
}


@app.middleware("http")
async def revalidar_sempre(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers.setdefault("Cache-Control", "no-cache")
    for nome, valor in CABECALHOS_DE_SEGURANCA.items():
        resposta.headers.setdefault(nome, valor)
    return resposta


# HEAD também: monitores externos (UptimeRobot, que mantém o Render free
# acordado) checam com HEAD por padrão; sem isto a rota devolve 405.
@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict[str, str]:
    return {"status": "ok"}


def _pagina_login(erro: str = "") -> str:
    """login.html. Sem `ACESSO_CONSULTORES`: nome livre + senha (como
    antes). Com a lista (decisão do usuário, 23/09/2026 — tela única): lista
    suspensa obrigatória com os nomes e, logo abaixo, a senha. O servidor
    confere o nome de novo.
    Consequência aceita: a página é pública, então os nomes da equipe
    aparecem para quem abrir o endereço, mesmo sem a senha."""
    pagina = (FRONTEND / "login.html").read_text(encoding="utf-8")
    if erro:
        pagina = pagina.replace("<!--ERRO-->", f'<p class="erro">{html.escape(erro)}</p>')
    nomes = consultores_permitidos()
    if not nomes:
        return pagina
    opcoes = "".join(
        f'<option value="{html.escape(n, quote=True)}">{html.escape(n)}</option>' for n in nomes
    )
    campos = (
        '<label for="nome">Escolha seu nome</label>'
        '<select id="nome" name="nome" required>'
        f'<option value="" disabled selected>Selecione…</option>{opcoes}</select>'
        '<label for="senha">Senha de acesso</label>'
        '<input type="password" id="senha" name="senha" required>'
    )
    inicio, fim = pagina.index("<!--CAMPOS-->"), pagina.index("<!--/CAMPOS-->")
    return pagina[:inicio] + campos + pagina[fim + len("<!--/CAMPOS-->"):]


# login.html é servido antes da sessão: não carrega os módulos do app.
@app.get("/login")
def pagina_de_login() -> HTMLResponse:
    return HTMLResponse(_pagina_login())


@app.post("/login")
def fazer_login(nome: str = Form(""), senha: str = Form(...)):
    if not senha_confere(senha):
        return HTMLResponse(_pagina_login("Senha incorreta."), status_code=401)

    equipe = consultores_permitidos()
    if equipe and nome not in equipe:
        return HTMLResponse(_pagina_login("Escolha seu nome na lista."), status_code=401)
    if not nome.strip():
        return HTMLResponse(_pagina_login("Informe seu nome."), status_code=401)

    resposta = RedirectResponse(url="/", status_code=303)
    resposta.set_cookie(
        NOME_DO_COOKIE,
        criar_cookie(nome),
        max_age=VALIDADE_COOKIE_S,
        httponly=True,
        samesite="lax",
        # `secure=True` por padrão (achado na auditoria de fechamento do
        # MVP, 21/09/2026, BLOCO 1): sem isto, o cookie de sessão viajaria
        # também por HTTP puro, se algum dia alguém acessasse por esse
        # caminho. Único opt-out: `ACESSO_COOKIE_INSEGURO=1`, para rodar
        # localmente em `http://localhost` sem HTTPS/túnel. Nunca usar em
        # produção (Render e o domínio do projeto são sempre HTTPS).
        secure=os.environ.get("ACESSO_COOKIE_INSEGURO", "").strip() != "1",
    )
    logger.info("login: consultor=%r", nome.strip() or "consultor")
    return resposta


class PedidoBusca(BaseModel):
    # Corte duro só contra abuso (corpo gigante ocupando memória). Fica bem
    # acima do limite real (MAX_CARACTERES = 1000 em busca/servico.py), que
    # continua respondendo com a mensagem amigável; a caixa do chat já tem
    # maxlength=1000, então o consultor nunca chega neste 422.
    texto: str = Field(max_length=5000)


@lru_cache
def buscador() -> BuscadorAtividades:
    # Criado no primeiro uso, e uma vez so: carrega e indexa a base oficial.
    return criar_buscador()


@app.post("/api/atividades/buscar", response_model=ResultadoBusca)
def buscar_atividade(pedido: PedidoBusca, request: Request) -> ResultadoBusca:
    """Descricao livre do consultor -> atividade oficial. Sempre responde
    200 com um ResultadoBusca; falha do LLM vem em `status`/`erro`.

    Guardrails de custo: só as buscas que chegam de fato ao LLM contam, na
    cota diária da pessoa (padrão 50) e no teto GLOBAL diário (padrão
    1500) — ver `CotaDaPessoa`. Busca sem LLM é ilimitada. Esgotado
    qualquer um, a busca segue sem LLM — nunca bloqueia o consultor.
    """
    # Cota diária de LLM por pessoa (nome do login; sem nome, a sessão).
    pessoa = getattr(request.state, "consultor", "") or getattr(request.state, "sessao_id", "")
    resultado = buscador().buscar(pedido.texto, cota=CotaDaPessoa(pessoa))
    resultado.usos_llm_restantes = contador_padrao.usos_llm_restantes(pessoa)
    resultado.limite_llm_dia = contador_padrao.limite_llm_por_pessoa
    return resultado


class CotaDaPessoa:
    """Liga a cota do buscador ao contador do processo (`backend/acesso.py`)."""

    def __init__(self, pessoa: str):
        self.pessoa = pessoa

    def consumir(self) -> str | None:
        bloqueio = contador_padrao.consumir_uso_llm(self.pessoa)
        # Auditoria: uma linha por busca inteligente, filtrável por nome no
        # log do Render (procure "cota LLM").
        logger.info(
            "cota LLM: consultor=%r %s — restam %d/%d",
            self.pessoa,
            f"BLOQUEADO ({bloqueio})" if bloqueio else "usou",
            contador_padrao.usos_llm_restantes(self.pessoa),
            contador_padrao.limite_llm_por_pessoa,
        )
        return bloqueio

    def devolver(self) -> None:
        contador_padrao.devolver_uso_llm(self.pessoa)
        logger.info("cota LLM: consultor=%r uso devolvido (falha do LLM)", self.pessoa)


@lru_cache
def base_em_json() -> tuple[bytes, str]:
    """Base serializada uma vez, com ETag = hash do conteúdo."""
    corpo = json.dumps(
        [a.model_dump(mode="json") for a in buscador().base.listar_atividades()],
        ensure_ascii=False,
    ).encode("utf-8")
    return corpo, f'"{hashlib.sha256(corpo).hexdigest()[:32]}"'


@app.get("/api/atividades")
def listar_atividades(request: Request) -> Response:
    """Base oficial inteira, na ordem da base, para a busca offline do
    celular (`frontend/busca-local.js`). Não conta no teto diário: não
    chama LLM. Com ETag: o app abre várias vezes por dia, e sem mudança na
    base a resposta é um 304 de poucos bytes em vez de ~0,5 MB."""
    corpo, etag = base_em_json()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(corpo, media_type="application/json", headers={"ETag": etag})


# Precisa vir depois das rotas: montado em "/", o StaticFiles captura
# qualquer caminho que nao tenha casado com uma rota declarada acima.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
