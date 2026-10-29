"""
Testes da busca de atividades (Fase 1B — Gabriel).

Todos determinísticos: nenhum teste aqui chama o LLM de verdade. O LLM
é substituído por `LLMFalso`, que devolve uma resposta roteirizada ou
levanta um erro — assim dá para testar o que acontece quando o modelo
inventa um ID, devolve lixo ou fica sem quota. Os testes com o modelo real
ficam em `test_busca_llm_real.py` e só rodam quando pedidos.

As atividades são referenciadas por (atividade, produto) e resolvidas para
ID pela própria base oficial, para não depender da numeração.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.busca import (
    BuscadorAtividades,
    ClienteClaude,
    RecuperadorLexical,
    StatusBusca,
)
from backend.busca.interpretador import SCHEMA_RESPOSTA, descrever_catalogo
from backend.busca.llm import (
    ErroApiIndisponivel,
    ErroChaveAusente,
    ErroLLM,
    ErroModeloIndisponivel,
    ErroQuota,
    ErroTimeout,
)
from backend.busca.modelos import Origem
from backend.busca.servico import MAX_OPCOES_DIRETAS, correspondencia_exata, correspondencia_por_nome
from backend.busca.texto import normalizar, radicais
from backend.busca.validador import RespostaInvalida, validar_resposta
from backend.dados import carregar_base_oficial


# ----------------------------------------------------------------------
# Apoio
# ----------------------------------------------------------------------


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


def ids(candidatos) -> list[int]:
    return [c.atividade.id for c in candidatos]


class LLMFalso:
    """Substitui o LLM. `resposta` pode ser texto, dict (vira JSON) ou
    uma exceção a levantar. Guarda cada chamada para inspeção."""

    modelo = "llm-falso"

    def __init__(self, resposta=None):
        self.resposta = resposta
        self.chamadas: list[tuple[str, dict | None]] = []

    def gerar(self, prompt, schema, sistema=None):
        self.chamadas.append((prompt, schema))
        self.sistema = sistema
        if isinstance(self.resposta, Exception):
            raise self.resposta
        if callable(self.resposta):
            return self.resposta(prompt)
        if isinstance(self.resposta, dict):
            return json.dumps(self.resposta)
        return self.resposta


def resposta(decisao, id_atividade=None, ids_possiveis=(), justificativa="ok"):
    return {
        "decisao": decisao,
        "id_atividade": id_atividade,
        "ids_possiveis": list(ids_possiveis),
        "justificativa": justificativa,
    }


def buscador_com(base, recuperador, llm) -> BuscadorAtividades:
    return BuscadorAtividades(base=base, recuperador=recuperador, cliente_llm=llm)


CONSIGNADO = ("Dúvida/Ajuda e Suporte (cliente)", "Crédito Consignado")
CONSIGNADO_UNIFICADO = ("Dúvida/Ajuda e Suporte (cliente)", "Crédito Consignado Unificado")
SENHA_DEBITO = ("Alteração/cadastro de Senha", "Cartão de Débito")


# ----------------------------------------------------------------------
# Normalização (porte do Chatbot.html)
# ----------------------------------------------------------------------


def test_normalizar_remove_acento_e_caixa():
    assert normalizar("Dúvida e CRÉDITO") == "duvida e credito"


def test_radicais_ignora_stopwords_e_reduz_variacoes():
    assert radicais("estou fazendo o cadastro") == radicais("cadastro")
    assert radicais("") == []
    assert radicais("de da do para") == []


# ----------------------------------------------------------------------
# Etapa A — recuperação (sem LLM)
# ----------------------------------------------------------------------


def test_recuperador_so_devolve_atividades_da_base_oficial(base, recuperador):
    for texto in ["dúvida consignado", "saque", "cartão senha", "malote"]:
        for c in recuperador.buscar(texto):
            assert base.atividade_por_id(c.atividade.id) == c.atividade


def test_descricao_semantica_traz_a_atividade_certa_entre_os_primeiros(base, recuperador):
    candidatos = recuperador.buscar(
        "Atendeu o cliente para tirar dúvida sobre empréstimo consignado."
    )
    assert id_de(base, *CONSIGNADO) in ids(candidatos)[:3]


def test_descricao_com_informacao_extra_ainda_recupera_a_atividade(base, recuperador):
    candidatos = recuperador.buscar(
        "Hoje de manhã, logo depois de abrir a agência, a gerente cadastrou a "
        "senha do cartão de débito de um senhor que estava com pressa"
    )
    assert id_de(base, *SENHA_DEBITO) in ids(candidatos)[:3]


def test_descricao_curta_recupera_pelo_produto(base, recuperador):
    candidatos = recuperador.buscar("malote")
    assert candidatos
    assert all("malote" in normalizar(c.atividade.produto + c.atividade.atividade)
               or "malote" in normalizar(c.atividade.subgrupo)
               for c in candidatos[:2])


def test_candidatos_trazem_evidencia_e_ordem_estavel(recuperador):
    primeira = recuperador.buscar("portabilidade de previdência")
    segunda = recuperador.buscar("portabilidade de previdência")
    assert ids(primeira) == ids(segunda)
    assert primeira[0].termos_casados == ["portabilidade", "previdencia"]
    assert [c.pontuacao for c in primeira] == sorted(
        (c.pontuacao for c in primeira), reverse=True
    )


def test_palavras_raras_pesam_mais_que_palavras_comuns(base, recuperador):
    # "consignado" é raro na base, "cliente" aparece em muitos registros.
    candidatos = recuperador.buscar("cliente consignado")
    assert "consignado" in normalizar(candidatos[0].atividade.produto)


@pytest.mark.parametrize(
    "texto, atividade, produto",
    [
        ("cliente pagou a parcela do acordo", "Pagamento de parcela", "Acordo (Dívida)"),
        ("transferiu dinheiro entre contas correntes", "Transferência entre contas", "Conta Corrente"),
        ("consultou o limite do cartão de crédito", "Consulta do limite do cartão", "Cartão de Crédito"),
    ],
)
def test_verbo_no_passado_casa_com_o_substantivo_da_base(base, recuperador, texto, atividade, produto):
    # Palavras diferentes das oficiais: "pagou" x "Pagamento", "transferiu" x "Transferência".
    assert ids(recuperador.buscar(texto))[0] == id_de(base, atividade, produto)


def test_limite_de_candidatos_e_respeitado(recuperador):
    assert len(recuperador.buscar("dúvida", limite=5)) == 5


def test_descricao_sem_relacao_com_a_base_nao_recupera_nada(recuperador):
    assert recuperador.buscar("fazendo café na copa") == []


# ----------------------------------------------------------------------
# Resolução determinística (sem LLM)
# ----------------------------------------------------------------------


def test_nome_oficial_exato_resolve_sem_chamar_o_llm(base, recuperador):
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar(
        "Pagamento de parcela - Acordo (Dívida)"
    )
    assert resultado.status == StatusBusca.ENCONTRADA
    assert resultado.origem == Origem.BUSCA
    assert resultado.atividade.id == id_de(base, "Pagamento de parcela", "Acordo (Dívida)")
    assert llm.chamadas == []


def test_palavra_a_mais_manda_para_o_llm(base):
    # Uma negação (ou qualquer palavra extra) impede a resolução exata.
    assert correspondencia_exata("não foi pagamento de parcela acordo divida", base) is None


def test_nome_igual_de_atividade_e_produto_nao_resolve_sozinho(base):
    # Existe o registro "Saque | Saque", mas "saque" sozinho também pode
    # ser "Saque com Cartão", "Saque no ATM"... — decisão fica com o LLM.
    assert correspondencia_exata("saque", base) is None


def test_so_o_nome_da_atividade_sem_produto_nao_resolve(base):
    assert correspondencia_exata("Dúvida/Ajuda e Suporte (cliente)", base) is None


def test_nome_de_atividade_unico_resolve_sem_llm(base, recuperador):
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar("acompanhamento de metas")
    assert resultado.status == StatusBusca.ENCONTRADA
    assert resultado.origem == Origem.BUSCA
    assert resultado.atividade.atividade == "Acompanhamento de metas"
    assert resultado.candidatos == []  # card único na tela
    assert llm.chamadas == []


def test_nome_com_poucas_opcoes_vira_lista_na_hora_sem_llm(base, recuperador):
    # "saque" é nome de produto com várias atividades: a escolha é do
    # consultor, e a lista sai direto da base.
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar("Saque")
    assert resultado.status == StatusBusca.AMBIGUA
    assert resultado.origem == Origem.BUSCA
    assert 2 <= len(resultado.alternativas) <= MAX_OPCOES_DIRETAS
    assert all(a.produto == "Saque" or a.atividade == "Saque" for a in resultado.alternativas)
    assert llm.chamadas == []


def test_nome_com_opcoes_demais_continua_indo_ao_llm(base, recuperador):
    # "Dúvida/Ajuda e Suporte (cliente)" existe para dezenas de produtos.
    llm = LLMFalso(resposta("nenhuma", justificativa="falta o produto"))
    buscador_com(base, recuperador, llm).buscar("Dúvida/Ajuda e Suporte (cliente)")
    assert len(llm.chamadas) == 1


def test_negacao_nao_entra_no_atalho_por_nome(base, recuperador):
    llm = LLMFalso(resposta("nenhuma", justificativa="negação"))
    buscador_com(base, recuperador, llm).buscar("não foi saque")
    assert len(llm.chamadas) == 1


def test_segunda_via_por_extenso_casa_com_2a_via(base, recuperador):
    candidatos = recuperador.buscar("segunda via do cartão")
    assert any("2ª via" in c.atividade.atividade for c in candidatos[:3])


def test_resposta_do_llm_fica_em_memoria_para_a_mesma_descricao(base, recuperador):
    alvo = id_de(base, *CONSIGNADO)
    llm = LLMFalso(resposta("encontrada", id_atividade=alvo))
    buscador = buscador_com(base, recuperador, llm)
    primeira = buscador.buscar("dúvida sobre consignado")
    segunda = buscador.buscar("  Dúvida sobre CONSIGNADO ")
    assert len(llm.chamadas) == 1
    assert segunda.atividade == primeira.atividade
    assert segunda.texto_original == "Dúvida sobre CONSIGNADO"


def test_falha_do_llm_nao_fica_em_memoria(base, recuperador):
    llm = LLMFalso(ErroQuota("quota"))
    buscador = buscador_com(base, recuperador, llm)
    buscador.buscar("dúvida sobre consignado")
    buscador.buscar("dúvida sobre consignado")
    assert len(llm.chamadas) == 2


# ----------------------------------------------------------------------
# Entradas que não chegam ao LLM
# ----------------------------------------------------------------------


@pytest.mark.parametrize("texto", ["", "   ", "?!...", "de da do para com"])
def test_entrada_vazia_ou_sem_palavras_relevantes(base, recuperador, texto):
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar(texto)
    assert resultado.status == StatusBusca.ENTRADA_INSUFICIENTE
    assert resultado.atividade is None
    assert llm.chamadas == []


def test_texto_longo_demais_e_recusado_sem_chamar_o_llm(base, recuperador):
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar("consignado " * 200)
    assert resultado.status == StatusBusca.ENTRADA_INSUFICIENTE
    assert llm.chamadas == []


def test_descricao_sem_pista_lexical_ainda_vai_ao_llm_com_o_catalogo(base, recuperador):
    # Decisão de 23/09/2026: "fui ao banheiro" não casa nenhuma palavra da
    # base, mas é Tempo Não Produtivo ("almoçar" deixou de servir de exemplo:
    # a tabela de 28/09 tem a atividade "Almoço") — quem liga uma coisa à outra é o LLM, que
    # agora vê o catálogo inteiro.
    tnp = next(a.id for a in base.listar_atividades() if "tempo n" in a.produto.lower())
    llm = LLMFalso(resposta("encontrada", id_atividade=tnp))
    resultado = buscador_com(base, recuperador, llm).buscar("fui ao banheiro")
    assert resultado.status == StatusBusca.ENCONTRADA
    assert resultado.atividade == base.atividade_por_id(tnp)
    assert resultado.candidatos == []
    assert len(llm.chamadas) == 1


def test_llm_recebe_o_catalogo_inteiro_e_as_definicoes_oficiais(base, recuperador):
    llm = LLMFalso(resposta("nenhuma", justificativa="vago"))
    buscador_com(base, recuperador, llm).buscar("cliente pedindo dinheiro para abrir um negócio")
    sistema = llm.sistema
    assert all(f"\n{a.id} | {a.atividade} |" in sistema for a in base.listar_atividades())
    assert "Capital de Giro: empréstimo para a empresa tocar o dia a dia" in sistema
    assert "Nunca crie um ID" in sistema
    prompt = llm.chamadas[0][0]
    assert "<<<cliente pedindo dinheiro para abrir um negócio>>>" in prompt
    assert "Capital de Giro" not in prompt  # parte variável fica pequena


def test_catalogo_e_identico_entre_buscas_para_o_cache_pegar(base, recuperador):
    llm = LLMFalso(resposta("nenhuma", justificativa="vago"))
    buscador = buscador_com(base, recuperador, llm)
    buscador.buscar("cliente com dúvida do consignado")
    primeiro = llm.sistema
    buscador.buscar("cliente pediu empréstimo")
    assert llm.sistema == primeiro


def test_id_fora_das_pistas_lexicais_mas_da_base_e_aceito(base, recuperador):
    outro = id_de(base, *SENHA_DEBITO)
    llm = LLMFalso(resposta("encontrada", id_atividade=outro))
    resultado = buscador_com(base, recuperador, llm).buscar("dúvida sobre consignado")
    assert outro not in ids(resultado.candidatos)
    assert resultado.atividade == base.atividade_por_id(outro)


def test_sacou_casa_com_saque(recuperador):
    primeiro = recuperador.buscar("cliente sacou dinheiro")[0].atividade
    assert "saque" in normalizar(primeiro.produto + " " + primeiro.atividade)


# ----------------------------------------------------------------------
# Etapa B — interpretação pelo LLM (simulado)
# ----------------------------------------------------------------------


def test_llm_escolhe_um_candidato_e_os_dados_vem_da_base(base, recuperador):
    alvo = id_de(base, *CONSIGNADO)
    llm = LLMFalso(resposta(
        "encontrada", alvo,
        justificativa="dúvida de cliente sobre consignado",
    ))
    resultado = buscador_com(base, recuperador, llm).buscar(
        "Atendeu o cliente para tirar dúvida sobre empréstimo consignado."
    )
    assert resultado.status == StatusBusca.ENCONTRADA
    assert resultado.origem == Origem.LLM
    assert resultado.atividade == base.atividade_por_id(alvo)
    assert resultado.justificativa == "dúvida de cliente sobre consignado"
    assert resultado.modelo == "llm-falso"
    assert len(llm.chamadas) == 1


def test_texto_do_llm_nunca_substitui_o_dado_oficial(base, recuperador):
    alvo = id_de(base, *CONSIGNADO)
    llm = LLMFalso(resposta(
        "encontrada", alvo,
        justificativa="Atividade: Empréstimo Consignado Premium (código 99)",
    ))
    resultado = buscador_com(base, recuperador, llm).buscar("dúvida sobre consignado")
    assert resultado.atividade.atividade == CONSIGNADO[0]
    assert resultado.atividade.produto == CONSIGNADO[1]


def test_duas_atividades_semelhantes_viram_ambigua(base, recuperador):
    a, b = id_de(base, *CONSIGNADO), id_de(base, *CONSIGNADO_UNIFICADO)
    llm = LLMFalso(resposta("ambigua", ids_possiveis=[a, b], justificativa="não diz qual consignado"))
    resultado = buscador_com(base, recuperador, llm).buscar("cliente com dúvida do consignado")
    assert resultado.status == StatusBusca.AMBIGUA
    assert resultado.atividade is None
    assert [x.id for x in resultado.alternativas] == [a, b]
    assert resultado.alternativas[0] == base.atividade_por_id(a)


def test_descricao_generica_demais_vira_sem_correspondencia(base, recuperador):
    llm = LLMFalso(resposta("nenhuma", justificativa="descrição genérica"))
    resultado = buscador_com(base, recuperador, llm).buscar("atendeu um cliente")
    assert resultado.status == StatusBusca.SEM_CORRESPONDENCIA
    assert resultado.origem == Origem.LLM
    assert resultado.atividade is None
    assert resultado.candidatos  # continuam disponíveis para escolha manual


def test_schema_e_enviado_ao_provedor_por_padrao(base, recuperador, monkeypatch):
    llm = LLMFalso(resposta("nenhuma"))
    buscador_com(base, recuperador, llm).buscar("dúvida consignado")
    assert llm.chamadas[0][1] == SCHEMA_RESPOSTA


# ----------------------------------------------------------------------
# Anti-alucinação — respostas do LLM que precisam ser recusadas
# ----------------------------------------------------------------------


@pytest.fixture
def candidatos(recuperador):
    return recuperador.buscar("dúvida sobre consignado")


def test_resposta_valida_com_cercas_markdown_e_aceita(base, candidatos):
    alvo = candidatos[0].atividade.id
    bruta = "```json\n" + json.dumps(resposta("encontrada", alvo)) + "\n```"
    assert validar_resposta(bruta, candidatos, base).atividade.id == alvo


def _recusada(bruta, candidatos, base) -> str:
    with pytest.raises(RespostaInvalida) as erro:
        validar_resposta(bruta, candidatos, base)
    return erro.value.motivo


def test_recusa_id_inexistente(base, candidatos):
    motivo = _recusada(json.dumps(resposta("encontrada", 9999)), candidatos, base)
    assert "9999" in motivo


def test_recusa_id_que_existe_na_base_mas_nao_estava_entre_os_candidatos(base, candidatos):
    fora = next(
        a.id for a in base.listar_atividades()
        if a.id not in {c.atividade.id for c in candidatos}
    )
    motivo = _recusada(json.dumps(resposta("encontrada", fora)), candidatos, base)
    assert "não estava entre os candidatos" in motivo


def test_recusa_id_como_string(base, candidatos):
    alvo = candidatos[0].atividade.id
    _recusada(json.dumps(resposta("encontrada", str(alvo))), candidatos, base)


@pytest.mark.parametrize("valor", [True, 1.0])
def test_recusa_id_booleano_ou_decimal(base, candidatos, valor):
    _recusada(json.dumps(resposta("encontrada", valor)), candidatos, base)


@pytest.mark.parametrize("bruta", ["", "   ", "```json\n```"])
def test_recusa_resposta_vazia(base, candidatos, bruta):
    assert "vazia" in _recusada(bruta, candidatos, base)


@pytest.mark.parametrize("bruta", ["{decisao: encontrada}", "Acho que é a 344.", "[1, 2"])
def test_recusa_json_invalido(base, candidatos, bruta):
    assert "JSON inválido" in _recusada(bruta, candidatos, base)


def test_recusa_json_que_nao_e_objeto(base, candidatos):
    _recusada("[344]", candidatos, base)


def test_recusa_campo_obrigatorio_ausente(base, candidatos):
    dados = resposta("encontrada", candidatos[0].atividade.id)
    del dados["justificativa"]
    assert "justificativa" in _recusada(json.dumps(dados), candidatos, base)


def test_recusa_campo_extra_inesperado(base, candidatos):
    dados = resposta("encontrada", candidatos[0].atividade.id)
    dados["atividade"] = "Nome inventado pelo modelo"
    assert "atividade" in _recusada(json.dumps(dados), candidatos, base)


def test_recusa_decisao_fora_do_dominio(base, candidatos):
    _recusada(json.dumps(resposta("talvez", candidatos[0].atividade.id)), candidatos, base)


def test_recusa_justificativa_vazia(base, candidatos):
    dados = resposta("encontrada", candidatos[0].atividade.id, justificativa="")
    _recusada(json.dumps(dados), candidatos, base)


def test_recusa_encontrada_sem_id(base, candidatos):
    _recusada(json.dumps(resposta("encontrada", None)), candidatos, base)


def test_recusa_encontrada_com_alternativas(base, candidatos):
    a, b = candidatos[0].atividade.id, candidatos[1].atividade.id
    _recusada(json.dumps(resposta("encontrada", a, [b])), candidatos, base)


def test_recusa_ambigua_com_menos_de_dois_ids(base, candidatos):
    a = candidatos[0].atividade.id
    _recusada(json.dumps(resposta("ambigua", ids_possiveis=[a, a])), candidatos, base)


def test_recusa_ambigua_com_um_id_inventado(base, candidatos):
    a = candidatos[0].atividade.id
    _recusada(json.dumps(resposta("ambigua", ids_possiveis=[a, 9999])), candidatos, base)


def test_recusa_nenhuma_com_id(base, candidatos):
    _recusada(json.dumps(resposta("nenhuma", candidatos[0].atividade.id)), candidatos, base)


def test_id_inventado_nunca_chega_ao_resultado_e_fica_registrado(
    base, recuperador, caplog
):
    llm = LLMFalso(resposta("encontrada", 9999))
    with caplog.at_level("WARNING", logger="backend.busca.servico"):
        resultado = buscador_com(base, recuperador, llm).buscar("dúvida sobre consignado")
    assert resultado.status == StatusBusca.RESPOSTA_INVALIDA
    assert resultado.atividade is None
    assert resultado.alternativas == []
    assert resultado.erro.tipo == "resposta_invalida"
    # O motivo técnico fica só no log do servidor, não na resposta da API.
    assert "9999" not in resultado.erro.mensagem
    assert resultado.candidatos  # a interface ainda pode oferecer escolha manual
    assert "9999" in caplog.text and "llm-falso" in caplog.text


def test_erro_cru_do_provedor_fica_so_no_log(base, recuperador, caplog):
    from backend.busca.llm import ErroQuota
    cru = "429: {'type': 'rate_limit_error', 'request_id': 'req_011abc'}"
    llm = LLMFalso(ErroQuota(f"limite da Anthropic atingido ({cru})"))
    with caplog.at_level("WARNING", logger="backend.busca.servico"):
        resultado = buscador_com(base, recuperador, llm).buscar("dúvida sobre consignado")
    assert resultado.status == StatusBusca.LLM_INDISPONIVEL
    assert resultado.erro.tipo == "quota_ou_limite"
    assert "req_011abc" not in resultado.erro.mensagem
    assert "429" not in resultado.erro.mensagem
    assert resultado.erro.mensagem  # mensagem fixa, não vazia
    assert "req_011abc" in caplog.text


# ----------------------------------------------------------------------
# Infraestrutura — falhas do LLM viram resultado previsível
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "erro, tipo",
    [
        (ErroQuota("429"), "quota_ou_limite"),
        (ErroTimeout("lento"), "timeout"),
        (ErroApiIndisponivel("rede"), "api_indisponivel"),
        (ErroModeloIndisponivel("404"), "modelo_indisponivel"),
        (ErroChaveAusente("sem chave"), "chave_ausente"),
        (ErroLLM("outro"), "erro_llm"),
    ],
)
def test_falha_do_llm_devolve_llm_indisponivel_com_candidatos(
    base, recuperador, erro, tipo
):
    resultado = buscador_com(base, recuperador, LLMFalso(erro)).buscar(
        "dúvida sobre consignado"
    )
    assert resultado.status == StatusBusca.LLM_INDISPONIVEL
    assert resultado.erro.tipo == tipo
    assert resultado.atividade is None
    assert resultado.candidatos


def test_sem_llm_configurado_devolve_candidatos(base, recuperador):
    resultado = buscador_com(base, recuperador, None).buscar("dúvida sobre consignado")
    assert resultado.status == StatusBusca.LLM_INDISPONIVEL
    assert resultado.candidatos


def test_chave_ausente_no_cliente_claude_real(base, recuperador, monkeypatch):
    monkeypatch.setattr("backend.busca.llm_anthropic.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resultado = buscador_com(base, recuperador, ClienteClaude()).buscar(
        "dúvida sobre consignado"
    )
    assert resultado.status == StatusBusca.LLM_INDISPONIVEL
    assert resultado.erro.tipo == "chave_ausente"


# ----------------------------------------------------------------------
# Rota HTTP (contrato consumido pela interface)
# ----------------------------------------------------------------------


def test_rota_de_busca_devolve_resultado_estruturado(base, recuperador, monkeypatch):
    from backend import main
    from backend.acesso import NOME_DO_COOKIE
    from conftest import cookie_autenticado

    alvo = id_de(base, *CONSIGNADO)
    falso = buscador_com(base, recuperador, LLMFalso(resposta("encontrada", alvo)))
    monkeypatch.setattr(main, "buscador", lambda: falso)

    http = TestClient(main.app)
    http.cookies.set(NOME_DO_COOKIE, cookie_autenticado())
    resposta_http = http.post(
        "/api/atividades/buscar", json={"texto": "dúvida sobre consignado"}
    )
    assert resposta_http.status_code == 200
    corpo = resposta_http.json()
    assert corpo["status"] == "encontrada"
    assert corpo["origem"] == "llm"
    assert corpo["atividade"]["id"] == alvo
    assert corpo["atividade"]["produto"] == CONSIGNADO[1]
    assert corpo["atividade"]["clientes_lista"]
    assert corpo["candidatos"][0]["atividade"]["id"]


def test_rota_responde_200_mesmo_com_llm_fora(base, recuperador, monkeypatch):
    from backend import main
    from backend.acesso import NOME_DO_COOKIE
    from conftest import cookie_autenticado

    falso = buscador_com(base, recuperador, LLMFalso(ErroQuota("429")))
    monkeypatch.setattr(main, "buscador", lambda: falso)

    http = TestClient(main.app)
    http.cookies.set(NOME_DO_COOKIE, cookie_autenticado())
    corpo = http.post(
        "/api/atividades/buscar", json={"texto": "dúvida sobre consignado"}
    ).json()
    assert corpo["status"] == "llm_indisponivel"
    assert corpo["erro"]["tipo"] == "quota_ou_limite"


def test_catalogo_marca_publico_e_segmento_de_cada_produto(base):
    # Capital de Giro é só PJ e não aceita Private; Crédito Pessoal é PF
    # e aceita — sem isto o LLM oferecia Capital de Giro a um cliente PF.
    catalogo = descrever_catalogo(base.listar_atividades())
    assert "## Capital de Giro (Empréstimo) [PJ · seg: MEI PE APJ]" in catalogo
    linha_pessoal = next(l for l in catalogo.splitlines() if l.startswith("## Crédito Pessoal (Emprestimo) ["))
    assert "PF" in linha_pessoal and " PV " in linha_pessoal
    assert "## Tempo não Produtivo [sem atendimento a cliente]" in catalogo


def test_tnp_do_proprio_consultor_marca_codigo_20(base, recuperador):
    tnp = id_de(base, "Tempo não produtivo", "Tempo não Produtivo")
    llm = LLMFalso({**resposta("encontrada", id_atividade=tnp), "tnp_do_consultor": True})
    resultado = buscador_com(base, recuperador, llm).buscar("fui almoçar")
    assert resultado.atividade.id == tnp
    assert resultado.tnp_do_consultor is True


def test_tnp_do_consultor_so_vale_sobre_tempo_nao_produtivo(base, recuperador):
    outra = id_de(base, *SENHA_DEBITO)
    llm = LLMFalso({**resposta("encontrada", id_atividade=outra), "tnp_do_consultor": True})
    resultado = buscador_com(base, recuperador, llm).buscar("cadastrei a senha do cartão")
    assert resultado.tnp_do_consultor is False


def test_catalogo_traz_publico_da_base_e_definicoes_do_projeto(base):
    from backend.busca.interpretador import montar_sistema_catalogo
    sistema = montar_sistema_catalogo(base.listar_atividades())
    assert "## Cheque Especial (Limite da conta) [PF · seg: V AR PV APF]" in sistema
    assert "## Cheque Empresa" in sistema
    assert "Private: segmento de clientes" in sistema
    assert "tnp_do_consultor" in sistema


def test_segmento_dito_tira_produto_incompativel_da_lista(base, recuperador):
    # O LLM ofereceu Capital de Giro (só PJ, sem Private) a um "cliente private".
    giro = id_de(base, "Oferta/Contratação", "Capital de Giro (Empréstimo)")
    pessoal = id_de(base, "Oferta/Contratação", "Crédito Pessoal (Emprestimo)")
    llm = LLMFalso(resposta("ambigua", ids_possiveis=[pessoal, giro]))
    resultado = buscador_com(base, recuperador, llm).buscar(
        "cliente private pedindo dinheiro para abrir um negócio"
    )
    assert resultado.status == StatusBusca.ENCONTRADA
    assert resultado.atividade.id == pessoal


def test_sem_publico_dito_a_lista_do_llm_fica_como_veio(base, recuperador):
    giro = id_de(base, "Oferta/Contratação", "Capital de Giro (Empréstimo)")
    pessoal = id_de(base, "Oferta/Contratação", "Crédito Pessoal (Emprestimo)")
    llm = LLMFalso(resposta("ambigua", ids_possiveis=[giro, pessoal], justificativa="PF ou PJ"))
    resultado = buscador_com(base, recuperador, llm).buscar("cliente pedindo dinheiro para abrir um negócio")
    assert [a.id for a in resultado.alternativas] == [giro, pessoal]
    assert resultado.justificativa == "PF ou PJ"


def test_filtro_nunca_esvazia_a_resposta(base):
    from backend.busca.servico import filtrar_por_publico
    giro = base.atividade_por_id(id_de(base, "Oferta/Contratação", "Capital de Giro (Empréstimo)"))
    assert filtrar_por_publico("cliente pf quer capital de giro", [giro]) == [giro]


def test_cheque_especial_nao_serve_para_pj(base):
    from backend.busca.servico import filtrar_por_publico
    cheque = [a for a in base.listar_atividades() if a.produto == "Cheque Especial (Limite da conta)"][:2]
    empresa = [a for a in base.listar_atividades() if a.produto == "Capital de Giro (Empréstimo)"][:1]
    assert filtrar_por_publico("cliente pj quer aumentar limite", cheque + empresa) == empresa


@pytest.mark.parametrize(
    "digitado, atividade",
    [
        ("acompanhamneto de metas", "Acompanhamento de metas"),
        ("contagen de numerarios", "Contagem de numerários"),
    ],
)
def test_erro_de_digitacao_no_nome_resolve_sem_llm(base, recuperador, digitado, atividade):
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar(digitado)
    assert resultado.status == StatusBusca.ENCONTRADA
    assert resultado.atividade.atividade == atividade
    assert "entendido como" in resultado.justificativa


def test_correcao_nao_mexe_em_palavra_curta_nem_empatada():
    from backend.busca.texto import CorretorDigitacao
    c = CorretorDigitacao(["Saque", "Saldo", "Emprestimo", "Empresimo"])
    assert c.corrigir("sauqe") == "saque"
    assert c.corrigir("sald") == "sald"        # até 4 letras: nunca corrige
    assert c.corrigir("emprestmo") == "emprestmo"  # empate: não corrige


def test_llm_recebe_o_texto_como_foi_digitado(base, recuperador):
    llm = LLMFalso(resposta("nenhuma", justificativa="vago"))
    buscador_com(base, recuperador, llm).buscar("cliente pediu portabilidae do salario hoje cedo")
    assert "portabilidae" in llm.chamadas[0][0]


@pytest.mark.parametrize(
    "sem_acento, com_acento",
    [
        ("cartao de credito", "cartão de crédito"),
        ("contagem de numerarios", "Contagem de numerários"),
        ("deposito", "depósito"),
        ("cambio", "câmbio"),
        ("gestao de equipe", "Gestão de equipe"),
        ("tempo nao produtivo", "Tempo não produtivo"),
        ("emissao de 2a via de cartao", "Emissão de 2ª via de cartão"),
    ],
)
def test_acento_e_maiuscula_nao_mudam_a_busca(base, recuperador, sem_acento, com_acento):
    assert correspondencia_por_nome(sem_acento, base) == correspondencia_por_nome(com_acento, base)
    assert correspondencia_exata(sem_acento, base) == correspondencia_exata(com_acento, base)
    assert ids(recuperador.buscar(sem_acento)) == ids(recuperador.buscar(com_acento))


def test_nome_de_produto_lista_todas_as_atividades_na_hora(base, recuperador):
    # "cartão de crédito" tem 35 atividades: antes ia ao LLM (6 s); agora a
    # lista sai direto — sem mais pista, não há o que o LLM escolher.
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar("cartao de credito")
    assert resultado.status == StatusBusca.AMBIGUA
    assert resultado.origem == Origem.BUSCA
    assert len(resultado.alternativas) > MAX_OPCOES_DIRETAS
    assert {a.produto for a in resultado.alternativas} == {"Cartão de Crédito"}


class CotaFalsa:
    def __init__(self, livres, motivo="limite_pessoal"):
        self.livres, self.devolvidos, self.motivo = livres, 0, motivo

    def consumir(self):
        if self.livres <= 0:
            return self.motivo
        self.livres -= 1
        return None

    def devolver(self):
        self.livres += 1
        self.devolvidos += 1


def test_cota_esgotada_segue_sem_llm_com_candidatos(base, recuperador):
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    resultado = buscador_com(base, recuperador, llm).buscar("dúvida sobre consignado", cota=CotaFalsa(0))
    assert resultado.status == StatusBusca.LLM_INDISPONIVEL
    assert resultado.erro.tipo == "limite_pessoal"
    assert resultado.candidatos
    assert resultado.consumiu_llm is False


def test_teto_global_esgotado_segue_sem_llm(base, recuperador):
    llm = LLMFalso(AssertionError("não deveria chamar o LLM"))
    cota = CotaFalsa(0, motivo="limite_diario")
    resultado = buscador_com(base, recuperador, llm).buscar("dúvida sobre consignado", cota=cota)
    assert resultado.status == StatusBusca.LLM_INDISPONIVEL
    assert resultado.erro.tipo == "limite_diario"
    assert resultado.candidatos


def test_busca_sem_llm_nao_gasta_cota(base, recuperador):
    cota = CotaFalsa(1)
    buscador_com(base, recuperador, LLMFalso(AssertionError("sem LLM"))).buscar("saque", cota=cota)
    assert cota.livres == 1


def test_memoria_nao_gasta_cota_e_falha_devolve(base, recuperador):
    alvo = id_de(base, *CONSIGNADO)
    buscador = buscador_com(base, recuperador, LLMFalso(resposta("encontrada", id_atividade=alvo)))
    cota = CotaFalsa(5)
    assert buscador.buscar("dúvida sobre consignado", cota=cota).consumiu_llm is True
    assert buscador.buscar("dúvida sobre consignado", cota=cota).consumiu_llm is False  # memória
    assert cota.livres == 4
    falho = buscador_com(base, recuperador, LLMFalso(ErroQuota("429")))
    assert falho.buscar("cliente pediu empréstimo", cota=cota).consumiu_llm is False
    assert cota.devolvidos == 1 and cota.livres == 4
