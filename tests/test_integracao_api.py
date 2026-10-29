"""
Testes de integração HTTP do pipeline de busca de atividades (Fase 1C).

Diferença para `tests/test_busca_atividades.py` (Fase 1B): aqueles testes
provam cada etapa isolada (recuperação, interpretação, validação); estes
provam a rota `POST /api/atividades/buscar` de ponta a ponta, como o
frontend de fato a consome — corpo da requisição, código HTTP e formato
da resposta.

Todos determinísticos: o LLM é substituído por `LLMFalso`, nunca há
chamada de rede real. Cobre os cenários pedidos na Fase 1C:

  1. fluxo positivo (descrição → candidatos → LLM → atividade oficial)
  2. sem correspondência
  3. LLM devolve atividade inexistente (rejeitada)
  4. LLM devolve atividade fora dos candidatos (rejeitada)
  5. LLM devolve JSON inválido
  6. entrada inválida (vazia e malformada)
  7. falha de infraestrutura do LLM (quota, timeout)

E confirma o critério de conclusão da Fase 1C: nenhuma resposta inválida
do LLM chega ao usuário como atividade oficial, e nenhum erro expõe chave
de API, stack trace ou detalhe interno desnecessário.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.busca import BuscadorAtividades, RecuperadorLexical
from backend.busca.llm import ErroQuota, ErroTimeout
from backend.dados import carregar_base_oficial

ROTA = "/api/atividades/buscar"


@pytest.fixture(scope="module")
def base():
    return carregar_base_oficial()


@pytest.fixture(scope="module")
def recuperador(base):
    return RecuperadorLexical(base)


def id_de(base, atividade: str, produto: str) -> int:
    achadas = [
        a.id for a in base.listar_atividades()
        if a.atividade == atividade and a.produto == produto
    ]
    assert len(achadas) == 1, f"({atividade!r}, {produto!r}) não está na base"
    return achadas[0]


class LLMFalso:
    """Mesma responsabilidade do `LLMFalso` de `test_busca_atividades.py`:
    substitui o LLM por uma resposta roteirizada, sem rede."""

    modelo = "llm-falso"

    def __init__(self, resposta=None):
        self.resposta = resposta

    def gerar(self, prompt, schema, sistema=None):
        if isinstance(self.resposta, Exception):
            raise self.resposta
        if isinstance(self.resposta, dict):
            return json.dumps(self.resposta)
        return self.resposta


def resposta_llm(decisao, id_atividade=None, ids_possiveis=(), justificativa="ok"):
    return {
        "decisao": decisao,
        "id_atividade": id_atividade,
        "ids_possiveis": list(ids_possiveis),
        "justificativa": justificativa,
    }


def usar_buscador(monkeypatch, base, recuperador, llm):
    """Troca o buscador usado pela rota por um com LLM controlado, sem
    tocar em variável global compartilhada entre testes (`monkeypatch`
    desfaz a troca automaticamente ao final de cada teste)."""
    falso = BuscadorAtividades(base=base, recuperador=recuperador, cliente_llm=llm)
    monkeypatch.setattr(main, "buscador", lambda: falso)
    return falso


CONSIGNADO = ("Dúvida/Ajuda e Suporte (cliente)", "Crédito Consignado")


# ----------------------------------------------------------------------
# 1. Fluxo positivo
# ----------------------------------------------------------------------


def test_fluxo_positivo_descricao_ate_atividade_oficial(cliente, base, recuperador, monkeypatch):
    alvo = id_de(base, *CONSIGNADO)
    usar_buscador(monkeypatch, base, recuperador, LLMFalso(resposta_llm("encontrada", alvo)))

    http = cliente.post(ROTA, json={"texto": "cliente com dúvida sobre o consignado"})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "encontrada"
    assert corpo["origem"] == "llm"
    assert corpo["atividade"]["id"] == alvo
    assert corpo["atividade"]["atividade"] == CONSIGNADO[0]
    assert corpo["atividade"]["produto"] == CONSIGNADO[1]
    # Dado oficial completo, não só o id - é o que o frontend exibe.
    assert corpo["atividade"]["subgrupo"]
    assert corpo["atividade"]["classificacao"]
    assert len(corpo["candidatos"]) >= 1


def test_fluxo_positivo_resolvido_so_pela_busca_sem_chamar_llm(cliente, base, recuperador, monkeypatch):
    # Nome exato da atividade + produto: resolve sem LLM (ver
    # `correspondencia_exata` em backend/busca/servico.py).
    usar_buscador(monkeypatch, base, recuperador, LLMFalso("NUNCA DEVERIA SER CHAMADO"))

    http = cliente.post(ROTA, json={"texto": f"{CONSIGNADO[0]} {CONSIGNADO[1]}"})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "encontrada"
    assert corpo["origem"] == "busca"


# ----------------------------------------------------------------------
# 2. Sem correspondência
# ----------------------------------------------------------------------


def test_sem_correspondencia_nao_inventa_atividade(cliente, base, recuperador, monkeypatch):
    usar_buscador(
        monkeypatch, base, recuperador, LLMFalso(resposta_llm("nenhuma", justificativa="fora do escopo"))
    )

    http = cliente.post(ROTA, json={"texto": "foi tomar um café na copa"})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "sem_correspondencia"
    assert corpo["atividade"] is None


# ----------------------------------------------------------------------
# 3 e 4. LLM inválido / fora dos candidatos - nunca vira atividade oficial
# ----------------------------------------------------------------------


def test_llm_devolve_id_inexistente_e_sistema_rejeita(cliente, base, recuperador, monkeypatch):
    usar_buscador(
        monkeypatch, base, recuperador, LLMFalso(resposta_llm("encontrada", 99_999_999))
    )

    http = cliente.post(ROTA, json={"texto": "cliente com dúvida sobre o consignado"})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "resposta_invalida"
    # Garantia central: nenhum objeto de atividade oficial é construído a
    # partir do ID inventado - nem em `atividade`, nem em `alternativas`.
    assert corpo["atividade"] is None
    assert corpo["alternativas"] == []
    assert corpo["erro"]["tipo"] == "resposta_invalida"
    # `candidatos` continua vindo só da base oficial (nunca do LLM).
    assert all(c["atividade"]["id"] != 99_999_999 for c in corpo["candidatos"])


def test_llm_escolhe_fora_das_pistas_lexicais_e_dados_vem_da_base(cliente, base, recuperador, monkeypatch):
    # Desde 23/09/2026 o LLM escolhe sobre o catálogo inteiro: ID real da
    # base, mesmo fora dos candidatos lexicais, é aceito — com os dados da base.
    outro_id = id_de(base, "Alteração/cadastro de Senha", "Cartão de Débito")
    usar_buscador(monkeypatch, base, recuperador, LLMFalso(resposta_llm("encontrada", outro_id)))

    http = cliente.post(ROTA, json={"texto": "cliente com dúvida sobre o consignado"})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "encontrada"
    assert corpo["atividade"]["id"] == outro_id
    assert corpo["atividade"]["produto"] == "Cartão de Débito"


# ----------------------------------------------------------------------
# 5. JSON inválido
# ----------------------------------------------------------------------


def test_llm_devolve_json_invalido_e_erro_e_controlado(cliente, base, recuperador, monkeypatch):
    usar_buscador(monkeypatch, base, recuperador, LLMFalso("isso não é JSON nenhum"))

    http = cliente.post(ROTA, json={"texto": "cliente com dúvida sobre o consignado"})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "resposta_invalida"
    assert corpo["atividade"] is None


# ----------------------------------------------------------------------
# 6. Entrada inválida
# ----------------------------------------------------------------------


def test_descricao_vazia_devolve_200_com_status_controlado(cliente):
    http = cliente.post(ROTA, json={"texto": ""})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "entrada_insuficiente"
    assert corpo["atividade"] is None


def test_campo_texto_ausente_devolve_erro_http_sem_expor_detalhe_interno(cliente):
    http = cliente.post(ROTA, json={})

    assert http.status_code == 422
    corpo = http.json()
    # Erro de validação padrão do FastAPI/Pydantic: aponta o campo, não
    # expõe stack trace nem caminho de arquivo do servidor.
    assert "traceback" not in json.dumps(corpo).lower()


def test_campo_texto_com_tipo_errado_devolve_erro_http(cliente):
    http = cliente.post(ROTA, json={"texto": 12345})

    assert http.status_code == 422


# ----------------------------------------------------------------------
# 7. Falha de infraestrutura do LLM
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "erro, tipo_esperado",
    [
        (ErroQuota("429 RESOURCE_EXHAUSTED: quota excedida"), "quota_ou_limite"),
        (ErroTimeout("o modelo não respondeu em 20s"), "timeout"),
    ],
)
def test_falha_de_infraestrutura_devolve_200_com_status_controlado(
    cliente, base, recuperador, monkeypatch, erro, tipo_esperado
):
    usar_buscador(monkeypatch, base, recuperador, LLMFalso(erro))

    http = cliente.post(ROTA, json={"texto": "cliente com dúvida sobre o consignado"})

    assert http.status_code == 200
    corpo = http.json()
    assert corpo["status"] == "llm_indisponivel"
    assert corpo["erro"]["tipo"] == tipo_esperado
    # Os candidatos da busca continuam disponíveis para escolha manual.
    assert len(corpo["candidatos"]) >= 1
    assert_sem_detalhe_interno(http)


# ----------------------------------------------------------------------
# Não vazar segredo nem detalhe interno em nenhuma resposta de erro
# ----------------------------------------------------------------------


def assert_sem_detalhe_interno(http):
    """Nenhuma resposta HTTP desta rota - erro ou não - pode conter
    traceback, caminho de arquivo do servidor ou o valor de uma chave de
    API. As mensagens de erro tipadas (`DetalheErro`) descrevem a
    categoria da falha (ex.: "quota ou limite atingido"), nunca o
    ambiente interno do servidor."""
    texto = http.text
    assert "Traceback" not in texto
    assert "site-packages" not in texto
    assert "backend\\" not in texto and "backend/" not in texto


def test_json_invalido_do_llm_nao_expoe_detalhe_interno(cliente, base, recuperador, monkeypatch):
    usar_buscador(monkeypatch, base, recuperador, LLMFalso("isso não é JSON nenhum"))

    http = cliente.post(ROTA, json={"texto": "cliente com dúvida sobre o consignado"})

    assert_sem_detalhe_interno(http)


def test_erro_de_validacao_de_entrada_nao_expoe_detalhe_interno(cliente):
    http = cliente.post(ROTA, json={})

    assert_sem_detalhe_interno(http)


# ----------------------------------------------------------------------
# Cache do navegador
# ----------------------------------------------------------------------


@pytest.mark.parametrize("caminho", ["/", "/chat-app.js", "/app.css", "/login"])
def test_frontend_sempre_revalida_para_deploy_chegar_ao_celular(cliente, caminho):
    # Sem isto o iPhone (app na Tela de Início) segurava JS antigo depois
    # do deploy (23/09/2026). "no-cache" = pode guardar, mas confere o
    # ETag antes de usar (304 barato quando nada mudou).
    resposta = cliente.get(caminho)
    assert resposta.status_code == 200
    assert resposta.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("caminho", ["/", "/login", "/health", "/api/atividades"])
def test_toda_resposta_leva_cabecalhos_de_seguranca(cliente, caminho):
    cab = cliente.get(caminho).headers
    assert "default-src 'self'" in cab["content-security-policy"]
    assert "frame-ancestors 'none'" in cab["content-security-policy"]
    assert cab["x-content-type-options"] == "nosniff"
    assert cab["x-frame-options"] == "DENY"
    assert cab["referrer-policy"] == "same-origin"
    assert cab["strict-transport-security"].startswith("max-age=")


@pytest.mark.parametrize("caminho", ["/docs", "/redoc", "/openapi.json"])
def test_documentacao_automatica_da_api_desligada(cliente, caminho):
    assert cliente.get(caminho).status_code == 404


def test_texto_gigante_recusado_mas_acima_de_1000_segue_amigavel(cliente):
    # >1000: mensagem amigável do buscador (200). >5000: corte duro (422).
    amigavel = cliente.post(ROTA, json={"texto": "saque " * 300})
    assert amigavel.status_code == 200
    assert "resuma" in amigavel.json()["justificativa"]
    assert cliente.post(ROTA, json={"texto": "a" * 5001}).status_code == 422


# ----------------------------------------------------------------------
# Base para a busca offline do celular
# ----------------------------------------------------------------------


def test_rota_de_atividades_entrega_a_base_inteira_na_ordem(cliente, base):
    http = cliente.get("/api/atividades")
    assert http.status_code == 200
    corpo = http.json()
    assert [a["id"] for a in corpo] == [a.id for a in base.listar_atividades()]
    assert {"atividade", "produto", "subgrupo", "clientes_lista"} <= corpo[0].keys()


def test_rota_de_atividades_exige_login():
    assert TestClient(main.app).get("/api/atividades").status_code == 401


def test_service_worker_e_publico_e_sem_dado():
    http = TestClient(main.app).get("/sw.js")
    assert http.status_code == 200
    assert "javascript" in http.headers["content-type"]
    assert http.headers["cache-control"] == "no-cache"


def test_base_sem_mudanca_responde_304_para_nao_baixar_de_novo(cliente):
    primeira = cliente.get("/api/atividades")
    etag = primeira.headers["etag"]
    segunda = cliente.get("/api/atividades", headers={"If-None-Match": etag})
    assert segunda.status_code == 304
    assert segunda.content == b""
    assert cliente.get("/api/atividades", headers={"If-None-Match": '"outra"'}).status_code == 200


def test_rota_informa_cota_e_bloqueia_llm_ao_esgotar(cliente, base, recuperador, monkeypatch):
    from backend.acesso import ContadorDeUso, LimitesDeUso
    monkeypatch.setattr(main, "contador_padrao", ContadorDeUso(LimitesDeUso(usos_llm_por_pessoa_dia=1)))
    alvo = id_de(base, *CONSIGNADO)
    usar_buscador(monkeypatch, base, recuperador, LLMFalso(resposta_llm("encontrada", alvo)))
    primeira = cliente.post(ROTA, json={"texto": "cliente com dúvida sobre o consignado"}).json()
    assert primeira["consumiu_llm"] is True
    assert primeira["usos_llm_restantes"] == 0 and primeira["limite_llm_dia"] == 1
    segunda = cliente.post(ROTA, json={"texto": "cliente pediu um empréstimo pessoal"}).json()
    assert segunda["status"] == "llm_indisponivel"
    assert segunda["erro"]["tipo"] == "limite_pessoal"
