"""
Desambiguação entre atividades parecidas (29/09/2026).

Achado do teste de campo: "funcionário indo abrir a loja no início do dia"
virava "Abertura do sistema no início da jornada" (Rotinas da Loja) em vez
de "Abertura e fechamento da loja" (Gestão Patrimonial). O Haiku decidia por
palavras em comum. A correção tem três partes, testadas aqui sem LLM real:

1. busca por palavras: "abrir" casa com "abertura", "agência" vale "loja",
   palavra de tempo não pontua;
2. o LLM preenche verbo/objeto/produto e compara os registros mais
   parecidos ANTES de decidir (schema e prompt);
3. o validador confere a decisão contra a própria comparação do modelo:
   se ele marcou o escolhido como OUTRO objeto, a resposta vira "ambigua"
   — nunca uma escolha que o próprio raciocínio do modelo contradiz.
"""

import json

import pytest

from backend.busca import BuscadorAtividades, RecuperadorLexical, StatusBusca
from backend.busca.interpretador import SCHEMA_RESPOSTA, montar_sistema_catalogo
from backend.busca.llm_anthropic import MAX_TOKENS_SAIDA
from backend.busca.servico import correspondencia_por_nome
from backend.busca.texto import radicais
from backend.busca.validador import validar_resposta
from backend.dados import carregar_base_oficial


@pytest.fixture(scope="module")
def base():
    return carregar_base_oficial()


@pytest.fixture(scope="module")
def recuperador(base):
    return RecuperadorLexical(base)


@pytest.fixture(scope="module")
def catalogo(recuperador, base):
    # O serviço valida contra o catálogo inteiro.
    from backend.busca.modelos import Candidato
    return [Candidato(atividade=a, pontuacao=0.0, termos_casados=[]) for a in base.listar_atividades()]


def id_de(base, atividade, produto):
    achadas = [a.id for a in base.listar_atividades() if (a.atividade, a.produto) == (atividade, produto)]
    assert len(achadas) == 1, (atividade, produto)
    return achadas[0]


LOJA = ("Abertura e fechamento da loja", "Gestão Patrimonial")
SISTEMA = ("Abertura do sistema no início da jornada", "Rotinas da Loja")
TNP = ("Tempo não produtivo", "Tempo não Produtivo")
ALMOCO = ("Almoço", "Tempo não Produtivo")


# ----------------------------------------------------------------------
# 1. Busca por palavras
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        "funcionário indo abrir a loja no início do dia",
        "abrindo a agência",
        "gerente fechou a agência no fim do expediente",
    ],
)
def test_abrir_ou_fechar_a_loja_traz_abertura_da_loja_em_primeiro(base, recuperador, texto):
    assert recuperador.buscar(texto, 10)[0].atividade.id == id_de(base, *LOJA)


def test_verbo_abrir_casa_com_abertura():
    assert radicais("abriu a loja") == radicais("abertura da loja")
    assert radicais("abrindo o cofre") == radicais("abertura do cofre")


def test_agencia_e_o_mesmo_que_loja():
    assert radicais("agência") == radicais("loja")


def test_palavra_de_tempo_nao_conta_como_atividade():
    assert radicais("abriu a loja no início do dia de manhã") == radicais("abriu a loja")
    assert radicais("fechou no fim do expediente") == radicais("fechou")


@pytest.mark.parametrize(
    "nome, par",
    [
        ("Abertura do sistema no início da jornada", SISTEMA),
        ("Migração de conta entre agências", ("Migração de conta entre agências", "Conta Corrente")),
    ],
)
def test_nome_oficial_continua_achado_pelo_proprio_nome(base, nome, par):
    assert [a.id for a in correspondencia_por_nome(nome, base)] == [id_de(base, *par)]


# ----------------------------------------------------------------------
# 2. O que o LLM recebe e precisa preencher
# ----------------------------------------------------------------------


def test_schema_pede_acao_e_comparacao_antes_da_decisao():
    campos = list(SCHEMA_RESPOSTA["properties"])
    assert campos[:3] == ["acao_observada", "comparacao", "decisao"]
    acao = SCHEMA_RESPOSTA["properties"]["acao_observada"]["properties"]
    assert set(acao) == {"verbo", "objeto", "produto"}
    item = SCHEMA_RESPOSTA["properties"]["comparacao"]["items"]["properties"]
    # Verbo e objeto separados também do lado do registro: com um campo
    # único o modelo copiava o nome inteiro ("abertura do sistema no início
    # da jornada") e não comparava "loja" com "sistema".
    assert set(item) == {"id", "verbo", "objeto", "produto", "mesmo_objeto"}


def test_sistema_explica_a_comparacao_e_o_vocabulario_da_loja(base):
    sistema = montar_sistema_catalogo(base.listar_atividades())
    assert "COMO DECIDIR" in sistema
    assert "não são o objeto" in sistema
    assert "sem repetir o nome inteiro" in sistema
    assert "Loja é como o banco chama a agência" in sistema
    assert sistema.rstrip().endswith(json.dumps(SCHEMA_RESPOSTA, ensure_ascii=False))


def test_limite_de_saida_comporta_a_comparacao():
    # A resposta com a comparação tem ~250–400 tokens; cortar no meio vira
    # JSON inválido (resposta recusada).
    assert MAX_TOKENS_SAIDA >= 600


# ----------------------------------------------------------------------
# 3. Validador: a decisão precisa bater com a comparação do próprio modelo
# ----------------------------------------------------------------------


def bruta(decisao, id_atividade=None, ids_possiveis=(), comparacao=None, **extra):
    dados = {
        "acao_observada": {"verbo": "abrir", "objeto": "loja", "produto": ""},
        "comparacao": comparacao or [],
        "decisao": decisao,
        "id_atividade": id_atividade,
        "ids_possiveis": list(ids_possiveis),
        "justificativa": "ok",
        **extra,
    }
    return json.dumps(dados)


def comp(id_, igual):
    return {"id": id_, "verbo": "x", "objeto": "y", "produto": "z", "mesmo_objeto": igual}


def test_decisao_coerente_com_a_comparacao_e_aceita(base, catalogo):
    loja, sistema = id_de(base, *LOJA), id_de(base, *SISTEMA)
    d = validar_resposta(
        bruta("encontrada", loja, comparacao=[comp(loja, True), comp(sistema, False)]), catalogo, base
    )
    assert d.decisao == "encontrada"
    assert d.atividade.id == loja


def test_outros_registros_com_o_mesmo_objeto_nao_derrubam_a_escolha(base, catalogo):
    # Medido em 29/09: "abriu uma conta corrente" marca Oferta/Abertura,
    # Aprovação e Formalização como o mesmo objeto (conta corrente) e escolhe
    # certo pelo verbo. "mesmo_objeto" não é "mesma atividade".
    loja, sistema = id_de(base, *LOJA), id_de(base, *SISTEMA)
    d = validar_resposta(
        bruta("encontrada", loja, comparacao=[comp(loja, True), comp(sistema, True)]), catalogo, base
    )
    assert d.decisao == "encontrada"
    assert d.atividade.id == loja


def test_escolhido_que_a_comparacao_diz_ser_diferente_vira_ambigua(base, catalogo):
    # Caso real (Haiku, 29/09): "foi tomar um café na copa" → escolheu Tempo
    # não produtivo com a comparação marcando TNP e Almoço como diferentes.
    tnp, almoco = id_de(base, *TNP), id_de(base, *ALMOCO)
    d = validar_resposta(
        bruta("encontrada", tnp, comparacao=[comp(almoco, False), comp(tnp, False)]), catalogo, base
    )
    assert d.decisao == "ambigua"
    assert [a.id for a in d.alternativas] == [tnp, almoco]


def test_escolhido_diferente_e_marcado_igual_a_outro_poe_o_outro_primeiro(base, catalogo):
    loja, sistema = id_de(base, *LOJA), id_de(base, *SISTEMA)
    d = validar_resposta(
        bruta("encontrada", sistema, comparacao=[comp(sistema, False), comp(loja, True)]), catalogo, base
    )
    assert d.decisao == "ambigua"
    assert [a.id for a in d.alternativas] == [loja, sistema]


def test_escolhido_diferente_sem_nada_mais_comparado_vira_nenhuma(base, catalogo):
    tnp = id_de(base, *TNP)
    d = validar_resposta(bruta("encontrada", tnp, comparacao=[comp(tnp, False)]), catalogo, base)
    assert d.decisao == "nenhuma"
    assert d.atividade is None


def test_id_da_comparacao_fora_da_base_e_ignorado(base, catalogo):
    loja = id_de(base, *LOJA)
    d = validar_resposta(
        bruta("encontrada", loja, comparacao=[comp(loja, True), comp(999999, True)]), catalogo, base
    )
    assert d.decisao == "encontrada"
    assert d.atividade.id == loja


def test_resposta_sem_os_campos_de_comparacao_continua_valida(base, catalogo):
    loja = id_de(base, *LOJA)
    antiga = {"decisao": "encontrada", "id_atividade": loja, "ids_possiveis": [], "justificativa": "ok"}
    assert validar_resposta(json.dumps(antiga), catalogo, base).atividade.id == loja


def test_comparacao_incompleta_nao_derruba_a_resposta(base, catalogo):
    loja = id_de(base, *LOJA)
    d = validar_resposta(
        bruta("encontrada", loja, comparacao=[{"id": loja, "mesmo_objeto": True}]), catalogo, base
    )
    assert d.atividade.id == loja


# ----------------------------------------------------------------------
# Serviço: resultado e registro da decisão
# ----------------------------------------------------------------------


class LLMRoteiro:
    modelo = "llm-falso"

    def __init__(self, texto):
        self.texto = texto

    def gerar(self, prompt, schema, sistema=None):
        return self.texto


def test_decisao_incoerente_chega_como_ambigua_com_mensagem_propria(base, recuperador):
    loja, sistema = id_de(base, *LOJA), id_de(base, *SISTEMA)
    llm = LLMRoteiro(bruta("encontrada", sistema, comparacao=[comp(sistema, False), comp(loja, True)]))
    r = BuscadorAtividades(base=base, recuperador=recuperador, cliente_llm=llm).buscar(
        "funcionário indo abrir a loja no início do dia"
    )
    assert r.status == StatusBusca.AMBIGUA
    assert [a.id for a in r.alternativas] == [loja, sistema]
    assert r.justificativa != "ok"


def test_decisao_do_llm_fica_registrada_no_log(base, recuperador, caplog):
    loja, sistema = id_de(base, *LOJA), id_de(base, *SISTEMA)
    llm = LLMRoteiro(bruta("encontrada", loja, comparacao=[comp(loja, True), comp(sistema, False)]))
    with caplog.at_level("INFO", logger="backend.busca.servico"):
        BuscadorAtividades(base=base, recuperador=recuperador, cliente_llm=llm).buscar(
            "funcionário indo abrir a loja no início do dia"
        )
    linha = next(r.getMessage() for r in caplog.records if "decisão do LLM" in r.getMessage())
    assert "funcionário indo abrir a loja no início do dia" in linha
    assert "encontrada" in linha and str(loja) in linha
    assert "objeto" in linha and "loja" in linha


# ----------------------------------------------------------------------
# Gabarito do café (29/09/2026, Manual de Coleta + Guia §1.4)
# ----------------------------------------------------------------------


def test_cafe_do_colaborador_e_tnp_18_e_nao_do_consultor(base):
    # "FOI tomar um café" = o colaborador mapeado → TNP 18, Tempo não
    # produtivo, com "café" no Detalhamento. "FUI tomar um café" seria o
    # próprio consultor → TNP 20 (TNP do Consultor), que este caso NÃO é.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from avaliar_busca import carregar_casos

    caso = next(c for c in carregar_casos(base, "gerais") if c["texto"] == "foi tomar um café na copa")
    assert caso["esperado"] == "encontrada"
    assert caso["ids_aceitos"] == {id_de(base, *TNP)}
    assert "limitacao_conhecida" not in caso
    assert base.atividade_por_id(id_de(base, *TNP)).subgrupo.startswith("Tempo não produtivo")
