"""
Testes da autenticação mínima e dos guardrails de custo
(`backend/acesso.py`, BLOCO 3 do plano de fechamento do MVP, CLAUDE.md).

Regra de negócio (ajustada duas vezes após a primeira versão do BLOCO 3 —
ver histórico de desenvolvimento no CLAUDE.md):
  - CHAT: a busca não tem limite por pessoa. Toda busca entra no teto
    global DE CHAT (`chamadas_globais_por_dia`, padrão 1500), como
    proteção contra abuso/erro; só as que chegam ao LLM gastam a cota
    diária por pessoa (`usos_llm_por_pessoa_dia`, padrão 60).
  (Guardrails de análise de PDF saíram junto com a rota, 22/09/2026.)

Cobre:
  1. `/login` e `/health` continuam públicos; tudo o mais exige sessão.
  2. senha certa cria a sessão (cookie assinado, com `sessao_id`); senha
     errada não.
  3. cookie inválido/adulterado é tratado como "sem sessão", nunca 500.
  4. o teto global de chat, isolado (`ContadorDeUso` direto) e através
     da rota HTTP real; chat sem limite individual.

NENHUM TESTE AQUI CHAMA O LLM DE VERDADE.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from conftest import SENHA_DE_TESTE, cookie_autenticado  # noqa: E402

from backend import main  # noqa: E402
from backend.acesso import (  # noqa: E402
    ContadorDeUso,
    LimitesDeUso,
    NOME_DO_COOKIE,
    _limites_do_ambiente,
    criar_cookie,
    senha_confere,
    validar_cookie,
)
# ==========================================================================
# 1/2 — senha, cookie, rotas públicas x protegidas
# ==========================================================================


def test_senha_confere_aceita_a_senha_certa():
    assert senha_confere(SENHA_DE_TESTE) is True


def test_senha_confere_rejeita_senha_errada():
    assert senha_confere("chuta-qualquer-coisa") is False


def test_cookie_valido_devolve_nome_e_sessao_id():
    sessao = validar_cookie(criar_cookie("Ana"))
    assert sessao is not None
    assert sessao.nome == "Ana"
    assert sessao.sessao_id  # não vazio


def test_cada_login_gera_um_sessao_id_novo():
    sessao_1 = validar_cookie(criar_cookie("Ana"))
    sessao_2 = validar_cookie(criar_cookie("Ana"))
    assert sessao_1.sessao_id != sessao_2.sessao_id


def test_cookie_ausente_e_none():
    assert validar_cookie(None) is None
    assert validar_cookie("") is None


def test_cookie_adulterado_e_none_nao_levanta():
    valido = criar_cookie("Ana")
    adulterado = valido[:-2] + "xx"
    assert validar_cookie(adulterado) is None


def test_health_e_publico_sem_cookie():
    resp = TestClient(main.app).get("/health")
    assert resp.status_code == 200


def test_health_aceita_head_sem_cookie():
    """UptimeRobot checa com HEAD; 405 contaria como app fora do ar."""
    resp = TestClient(main.app).head("/health")
    assert resp.status_code == 200


def test_pagina_de_login_e_publica_sem_cookie():
    resp = TestClient(main.app).get("/login")
    assert resp.status_code == 200
    assert "Cronoan" in resp.text  # a página existe e é servida de verdade


def test_login_com_senha_certa_cria_sessao_valida():
    http = TestClient(main.app)
    resp = http.post(
        "/login", data={"nome": "Ana", "senha": SENHA_DE_TESTE}, follow_redirects=False
    )
    assert resp.status_code == 303
    cookie = resp.cookies.get(NOME_DO_COOKIE)
    assert cookie is not None
    assert validar_cookie(cookie).nome == "Ana"


def test_login_com_senha_errada_nao_cria_sessao():
    http = TestClient(main.app)
    resp = http.post(
        "/login", data={"nome": "Ana", "senha": "errada"}, follow_redirects=False
    )
    assert resp.status_code == 401
    assert NOME_DO_COOKIE not in resp.cookies


def test_api_sem_cookie_devolve_401_json():
    resp = TestClient(main.app).post(
        "/api/atividades/buscar", json={"texto": "qualquer coisa"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]


def test_frontend_sem_cookie_redireciona_para_login():
    resp = TestClient(main.app).get("/index.html", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_frontend_com_cookie_nao_redireciona(cliente):
    resp = cliente.get("/index.html", follow_redirects=False)
    assert resp.status_code == 200


# ==========================================================================
# Regressão: leitura de limite por variável de ambiente (`_limites_do_ambiente`)
# ==========================================================================
#
# Achada no smoke test do ajuste de guardrails: `ACESSO_LIMITE_GLOBAL_DIA=0`
# era ignorado (caía no padrão de 300) e uma chamada real ao LLM
# aconteceu apesar do teto configurado para bloquear tudo. `0` precisa ser
# um valor explícito e respeitado -- só negativo/inválido cai no padrão.


@pytest.mark.parametrize(
    "nome_env,campo",
    [
        ("ACESSO_LIMITE_GLOBAL_DIA", "chamadas_globais_por_dia"),
    ],
)
def test_limite_do_ambiente_zero_e_respeitado_nao_cai_no_padrao(monkeypatch, nome_env, campo):
    monkeypatch.setenv(nome_env, "0")
    limites = _limites_do_ambiente()
    assert getattr(limites, campo) == 0


def test_limite_do_ambiente_negativo_cai_no_padrao(monkeypatch):
    monkeypatch.setenv("ACESSO_LIMITE_GLOBAL_DIA", "-5")
    limites = _limites_do_ambiente()
    assert limites.chamadas_globais_por_dia == LimitesDeUso.chamadas_globais_por_dia


def test_limite_do_ambiente_ausente_usa_o_padrao(monkeypatch):
    monkeypatch.delenv("ACESSO_LIMITE_GLOBAL_DIA", raising=False)
    limites = _limites_do_ambiente()
    assert limites.chamadas_globais_por_dia == LimitesDeUso.chamadas_globais_por_dia


def test_defaults_de_teto_global_sao_os_novos_valores_de_negocio():
    """Trava o teto de chat (1500) para não regredir em silêncio."""
    assert LimitesDeUso().chamadas_globais_por_dia == 1500


# ==========================================================================
# 4 — guardrails de custo, isolados (ContadorDeUso direto)
# ==========================================================================


def test_teto_global_so_conta_uso_de_llm():
    """Busca sem LLM não passa pelo contador: só `consumir_uso_llm` gasta o
    teto global, e o teto vale para a soma de todas as pessoas."""
    contador = ContadorDeUso(LimitesDeUso(chamadas_globais_por_dia=2, usos_llm_por_pessoa_dia=50))
    assert contador.consumir_uso_llm("Ana") is None
    assert contador.consumir_uso_llm("Bruno") is None
    assert contador.consumir_uso_llm("Carla") == "limite_diario"
    contador.devolver_uso_llm("Bruno")  # falha do LLM devolve nos dois
    assert contador.consumir_uso_llm("Carla") is None


# ==========================================================================
# 4 — guardrails através da rota HTTP de verdade
# ==========================================================================


def test_d_multiplas_consultas_de_chat_continuam_permitidas(cliente):
    """Sem limite individual: o chat continua respondendo 200."""
    for _ in range(10):
        resp = cliente.post("/api/atividades/buscar", json={"texto": ""})
        assert resp.status_code == 200  # entrada_insuficiente, sem chamar o LLM


def test_e_teto_global_esgotado_nao_bloqueia_busca_sem_llm(cliente, monkeypatch):
    """Teto global só limita o LLM: busca por palavras segue respondendo."""
    contador = ContadorDeUso(LimitesDeUso(chamadas_globais_por_dia=0))
    monkeypatch.setattr(main, "contador_padrao", contador)

    resp = cliente.post("/api/atividades/buscar", json={"texto": "qualquer coisa"})
    assert resp.status_code == 200


# ----------------------------------------------------------------------
# Cota diária de LLM por pessoa (23/09/2026)
# ----------------------------------------------------------------------


def test_cota_de_llm_por_pessoa_e_por_dia():
    from backend.acesso import ContadorDeUso, LimitesDeUso
    contador = ContadorDeUso(LimitesDeUso(usos_llm_por_pessoa_dia=2))
    assert contador.consumir_uso_llm("Ana") is None and contador.consumir_uso_llm(" ana ") is None
    assert contador.consumir_uso_llm("ANA") == "limite_pessoal"  # mesmo nome, cota acabou
    assert contador.usos_llm_restantes("Ana") == 0
    assert contador.consumir_uso_llm("Bruno") is None     # cada pessoa tem a sua
    contador.devolver_uso_llm("Ana")
    assert contador.usos_llm_restantes("Ana") == 1


def test_cota_vira_a_meia_noite_de_brasilia(monkeypatch):
    from backend.acesso import ContadorDeUso, LimitesDeUso
    contador = ContadorDeUso(LimitesDeUso(usos_llm_por_pessoa_dia=1))
    monkeypatch.setattr(contador, "_hoje", lambda: "2026-10-05")
    assert contador.consumir_uso_llm("ana") is None
    assert contador.consumir_uso_llm("ana") == "limite_pessoal"
    monkeypatch.setattr(contador, "_hoje", lambda: "2026-10-06")
    assert contador.consumir_uso_llm("ana") is None


def test_limite_zero_de_llm_e_respeitado(monkeypatch):
    from backend.acesso import ContadorDeUso
    monkeypatch.setenv("ACESSO_LIMITE_LLM_PESSOA_DIA", "0")
    assert ContadorDeUso().consumir_uso_llm("ana") == "limite_pessoal"


def test_dia_do_contador_e_o_de_brasilia():
    from datetime import datetime
    from backend.acesso import FUSO_BRASILIA, ContadorDeUso
    assert ContadorDeUso()._hoje() == datetime.now(FUSO_BRASILIA).date().isoformat()


# ----------------------------------------------------------------------
# Lista de consultores no login (23/09/2026)
# ----------------------------------------------------------------------

EQUIPE = "Ísis Januário da Costa; Ana Carolina Soares Ramos\nBruno Sant’Anna Castro Pedro"


def test_lista_de_consultores_em_ordem_sem_acento(monkeypatch):
    from backend.acesso import consultores_permitidos
    monkeypatch.setenv("ACESSO_CONSULTORES", EQUIPE)
    assert consultores_permitidos() == [
        "Ana Carolina Soares Ramos", "Bruno Sant’Anna Castro Pedro", "Ísis Januário da Costa",
    ]


def test_com_lista_a_tela_tem_so_a_lista_e_a_senha(monkeypatch):
    monkeypatch.setenv("ACESSO_CONSULTORES", EQUIPE)
    pagina = TestClient(main.app).get("/login").text
    lista = pagina.index('<select id="nome" name="nome" required>')
    senha = pagina.index('name="senha"')
    assert lista < senha
    assert 'id="filtro-nome"' not in pagina and 'type="text"' not in pagina
    assert "Bruno Sant’Anna Castro Pedro" in pagina


def test_nome_da_lista_com_senha_certa_entra(monkeypatch):
    monkeypatch.setenv("ACESSO_CONSULTORES", EQUIPE)
    http = TestClient(main.app)
    entrou = http.post(
        "/login", data={"senha": SENHA_DE_TESTE, "nome": "Bruno Sant’Anna Castro Pedro"},
        follow_redirects=False,
    )
    assert entrou.status_code == 303
    assert validar_cookie(entrou.cookies[NOME_DO_COOKIE]).nome == "Bruno Sant’Anna Castro Pedro"


def test_senha_errada_nao_entra(monkeypatch):
    monkeypatch.setenv("ACESSO_CONSULTORES", EQUIPE)
    resp = TestClient(main.app).post(
        "/login", data={"senha": "errada", "nome": "Ana Carolina Soares Ramos"}, follow_redirects=False
    )
    assert resp.status_code == 401 and NOME_DO_COOKIE not in resp.cookies


def test_nome_fora_da_lista_e_recusado(monkeypatch):
    monkeypatch.setenv("ACESSO_CONSULTORES", EQUIPE)
    resp = TestClient(main.app).post(
        "/login", data={"senha": SENHA_DE_TESTE, "nome": "Fulano"}, follow_redirects=False
    )
    assert resp.status_code == 401 and NOME_DO_COOKIE not in resp.cookies


def test_sem_lista_o_login_continua_com_nome_livre(monkeypatch):
    monkeypatch.delenv("ACESSO_CONSULTORES", raising=False)
    pagina = TestClient(main.app).get("/login").text
    assert 'name="nome"' in pagina and 'type="text"' in pagina


def test_login_antigo_com_nome_fora_da_lista_precisa_entrar_de_novo(monkeypatch):
    monkeypatch.setenv("ACESSO_CONSULTORES", EQUIPE)
    antigo = TestClient(main.app)
    antigo.cookies.set(NOME_DO_COOKIE, cookie_autenticado("ana"))  # digitado à mão
    assert antigo.get("/api/atividades").status_code == 401
    novo = TestClient(main.app)
    novo.cookies.set(NOME_DO_COOKIE, cookie_autenticado("Ana Carolina Soares Ramos"))
    assert novo.get("/api/atividades").status_code == 200
