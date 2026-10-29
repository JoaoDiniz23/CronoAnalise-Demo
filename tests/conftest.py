"""
Fixtures compartilhadas por toda a suíte.

BLOCO 3 do plano de fechamento do MVP (CLAUDE.md, 20/09/2026) acrescentou
autenticação mínima (`backend/acesso.py`) na frente de toda rota — inclusive
as que já tinham teste de integração HTTP (`test_integracao_api.py`,
`test_busca_atividades.py`). Este arquivo garante que:

1. Nenhum teste depende do `ACESSO_SENHA`/`ACESSO_SECRET_KEY` reais desta
   máquina (`.env`) — cada teste roda com um segredo de teste isolado.
2. `TestClient(main.app)` continua utilizável do mesmo jeito de antes para
   testes que não são sobre autenticação em si: a fixture `cliente` já
   vem com uma sessão válida.
"""

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.acesso import NOME_DO_COOKIE, ContadorDeUso, LimitesDeUso, criar_cookie

SEGREDO_DE_TESTE = "segredo-de-teste-para-a-suite-nao-usar-em-producao"
SENHA_DE_TESTE = "senha-de-teste-para-a-suite"


@pytest.fixture(autouse=True)
def _acesso_isolado_de_teste(monkeypatch):
    monkeypatch.setenv("ACESSO_SECRET_KEY", SEGREDO_DE_TESTE)
    monkeypatch.setenv("ACESSO_SENHA", SENHA_DE_TESTE)
    # Contador próprio por teste: a cota diária de LLM por pessoa não pode
    # vazar de um teste para outro (senão a suíte "estoura" os 50 usos).
    monkeypatch.setattr(main, "contador_padrao", ContadorDeUso(LimitesDeUso()))


def cookie_autenticado(nome: str = "consultor de teste") -> str:
    """Valor pronto do cookie de sessão — para testes que montam o
    `TestClient` na mão em vez de usar a fixture `cliente`."""
    return criar_cookie(nome)


@pytest.fixture
def cliente():
    """`TestClient` com sessão já válida. Rotas protegidas (tudo, exceto
    `/health` e `/login`) respondem normalmente; testes que precisam
    justamente de um cliente SEM sessão devem montar o próprio
    `TestClient(main.app)`, sem esta fixture."""
    http = TestClient(main.app)
    http.cookies.set(NOME_DO_COOKIE, cookie_autenticado())
    return http
