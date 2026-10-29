"""
Testes da camada de acesso a base oficial do cliente.

Dois grupos:

1. Testes sobre a base REAL do projeto - garantem que os arquivos em
   `dados/` continuam integros e que os dominios lidos do molde oficial
   (classificacao 1-20 sem o 7, codigo 8 presente, codigo 20 presente,
   atendimento ate o 6, legenda de Segmento presente) nao foram
   perdidos por uma edicao distraida.

   FONTE desses dominios: "Formulario de Coleta - Molde Final_CORRETO_
   Envio PUC_OFICIAL.pdf" (conteudos importantes/), reforcado pelo
   "Guia de atualizacao - o que mudou (EJs).pdf". Um teste aqui so muda
   se a fonte oficial mudar.

2. Testes sobre bases sinteticas em memoria - garantem que a camada
   RECUSA dados invalidos de forma ruidosa, em vez de seguir em frente
   com base corrompida.
"""

import pytest

from backend.dados import BaseOficial, ErroBaseOficial, carregar_base_oficial


# --------------------------------------------------------------------------
# 1. Base real do projeto
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def base() -> BaseOficial:
    return carregar_base_oficial()


def test_carrega_a_base_real_do_projeto(base):
    # Base FICTÍCIA de demonstração.
    assert len(base.atividades) == 139


def test_atividade_traz_todos_os_campos_oficiais(base):
    atividade = base.atividade_por_id(1)

    assert atividade is not None
    assert atividade.id == 1
    assert atividade.atividade
    assert atividade.produto
    assert atividade.subgrupo
    assert atividade.clientes
    assert atividade.segmento
    assert atividade.atendimento
    assert atividade.classificacao


def test_verifica_se_uma_atividade_existe(base):
    assert base.atividade_existe(1)
    assert base.atividade_existe(139)
    assert not base.atividade_existe(140)
    assert not base.atividade_existe(0)
    assert not base.atividade_existe(817)
    assert not base.atividade_existe(0)


def test_atividade_inexistente_devolve_none_em_vez_de_erro(base):
    assert base.atividade_por_id(99_999) is None


def test_classificacao_oficial_vai_de_1_a_20_sem_o_codigo_7(base):
    # Molde oficial, coluna da Classificacao: a numeracao pula de 6 para 8.
    assert sorted(base.codigos_classificacao()) == [
        1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20
    ]


def test_codigo_8_treinamento_existe_e_nao_foi_excluido(base):
    assert base.codigo_classificacao_existe(8)
    assert "Treinamento" in base.descricao_classificacao(8)


def test_codigo_7_nao_existe(base):
    # Guia de atualizacao, secao 2.1: "Nao existe o numero 7 - nem em
    # Local, nem em Classificacao. A numeracao pula de 6 para 8
    # justamente para o 7 nao ser confundido com o 1 na leitura da folha."
    assert not base.codigo_classificacao_existe(7)
    assert base.descricao_classificacao(7) is None


def test_codigo_13_e_pendencia_regulatoria(base):
    # Molde oficial: "13 - O: Pendencia regulatoria" (com acento na fonte).
    # E o mesmo texto do subgrupo "Pendencia regulatoria + Operacional"
    # da base de atividades.
    assert base.codigo_classificacao_existe(13)
    assert base.descricao_classificacao(13) == "O: Pendência regulatória"


def test_codigo_20_e_tnp_do_consultor(base):
    # Molde oficial: "20 - TNP: TNP do Consultor". O Manual (p. 37) e o
    # Guia (secao 1.4) confirmam: e o tempo parado do consultor, nao o
    # do colaborador mapeado (que e o codigo 18).
    assert base.codigo_classificacao_existe(20)
    assert base.descricao_classificacao(20) == "TNP: TNP do Consultor"


def test_local_da_atividade_tambem_pula_o_codigo_7(base):
    assert sorted(base.local_da_atividade) == [1, 2, 3, 4, 5, 6, 8]


def test_forma_de_atendimento_vai_ate_o_codigo_6_chat_c2_c5(base):
    # Molde oficial: "6 - Chat." O Guia (secao 2.2) marca como
    # "Novo. Nunca foi mapeado em anos anteriores" - por isso faltava.
    assert sorted(base.forma_de_atendimento) == [1, 2, 3, 4, 5, 6]
    assert base.forma_de_atendimento[6] == "Chat"


def test_segmento_tem_a_legenda_oficial_impressa_no_molde(base):
    # A legenda de Segmento existe: esta impressa no canto superior
    # direito do molde, em duas colunas, com 14 siglas.
    assert base.segmento_legenda is not None
    assert sorted(base.segmento_legenda) == sorted([
        "V", "AR", "PV", "MEI", "PE",
        "APF", "APJ", "SNI", "Não", "NCB",
    ])
    assert base.segmento_legenda["AR"] == "Alta Renda"
    assert base.segmento_legenda["SNI"] == "Segmento não Identificado"
    assert base.segmento_legenda["NCB"] == "Não cliente do Banco"


def test_siglas_de_segmento_impressas_sem_descricao_ficam_sem_descricao(base):
    # Sigla sem descricao na legenda fica None (nada e inventado).
    from backend.dados.base import BaseOficial as B
    import yaml
    from backend.dados.base import ARQUIVO_LEGENDA
    bruta = yaml.safe_load(ARQUIVO_LEGENDA.read_text(encoding="utf-8"))
    bruta["segmento"]["XX"] = None
    assert B([a.model_dump(exclude={"clientes_lista", "segmento_lista", "atendimento_lista"}) for a in base.atividades], bruta).segmento_legenda["XX"] is None


def test_campos_multivalor_sao_expostos_como_lista_sem_alterar_o_bruto(base):
    # id 2 tem varios clientes; o valor bruto continua fiel a fonte oficial
    # e a lista e apenas uma leitura mecanica dele.
    atividade = base.atividade_por_id(2)

    assert atividade.clientes == "Pessoa Juridica, Pessoa Fisica"
    assert atividade.clientes_lista == ["Pessoa Juridica", "Pessoa Fisica"]


def test_valores_distintos_de_um_campo_multivalor(base):
    assert base.valores_distintos("atendimento") == [
        "Chat",
        "E-mail",
        "Ligação de Voz",
        "Não foi um atendimento ao cliente",
        "Outros",
        "Presencial",
    ]


def test_valores_distintos_de_um_campo_simples(base):
    assert base.valores_distintos("classificacao") == [
        "Comercial", "Operacional", "Tempo não Produtivo"
    ]


def test_outras_legendas_oficiais_ficam_acessiveis(base):
    assert base.local_da_atividade[1] == "ATM"
    assert base.forma_de_atendimento[5] == "Presencial"
    # Acentuado, como esta impresso no molde.
    assert base.clientes_legenda[3] == "Não cliente do Banco"


def test_legenda_de_segmento_nao_e_de_para_dos_valores_da_base(base):
    # A legenda tem 10 siglas; o campo `segmento` da base tem 8 valores.
    # A correspondencia entre as duas NAO esta confirmada pelo cliente
    # e por isso nao existe em codigo.
    assert len(base.segmento_legenda) == 10
    assert len(base.valores_distintos("segmento")) == 8


# --------------------------------------------------------------------------
# 2. Recusa de dados invalidos
# --------------------------------------------------------------------------

LEGENDA_VALIDA = {
    "classificacao": {n: f"C: desc {n}" for n in range(1, 21) if n != 7},
    "local_da_atividade": {1: "ATM"},
    "forma_de_atendimento": {1: "E-mail"},
    "clientes": {1: "Cliente PF"},
    "segmento": None,
}

ATIVIDADE_VALIDA = {
    "id": 1,
    "atividade": "Abertura de Caixa",
    "produto": "Caixa",
    "subgrupo": "Numerário + Operacional",
    "clientes": "Não foi um atendimento ao cliente",
    "segmento": "Não atendimento ao cliente",
    "atendimento": "Não foi um atendimento ao cliente",
    "classificacao": "Operacional",
}


def test_recusa_base_com_id_duplicado():
    duplicado = [ATIVIDADE_VALIDA, {**ATIVIDADE_VALIDA, "atividade": "Outra"}]

    with pytest.raises(ErroBaseOficial, match="id"):
        BaseOficial(duplicado, LEGENDA_VALIDA)


def test_recusa_base_com_atividade_e_produto_repetidos():
    repetido = [ATIVIDADE_VALIDA, {**ATIVIDADE_VALIDA, "id": 2}]

    with pytest.raises(ErroBaseOficial, match="atividade.*produto"):
        BaseOficial(repetido, LEGENDA_VALIDA)


def test_recusa_atividade_com_campo_obrigatorio_vazio():
    vazio = [{**ATIVIDADE_VALIDA, "produto": "   "}]

    with pytest.raises(ErroBaseOficial, match="produto"):
        BaseOficial(vazio, LEGENDA_VALIDA)


def test_recusa_atividade_com_campo_faltando():
    incompleta = {k: v for k, v in ATIVIDADE_VALIDA.items() if k != "segmento"}

    with pytest.raises(ErroBaseOficial):
        BaseOficial([incompleta], LEGENDA_VALIDA)


def test_recusa_legenda_que_perdeu_o_codigo_8():
    sem_8 = {
        **LEGENDA_VALIDA,
        "classificacao": {
            n: d for n, d in LEGENDA_VALIDA["classificacao"].items() if n != 8
        },
    }

    with pytest.raises(ErroBaseOficial, match="classificação"):
        BaseOficial([ATIVIDADE_VALIDA], sem_8)


def test_recusa_legenda_que_ganhou_o_codigo_7():
    com_7 = {
        **LEGENDA_VALIDA,
        "classificacao": {**LEGENDA_VALIDA["classificacao"], 7: "C: inventado"},
    }

    with pytest.raises(ErroBaseOficial, match="classificação"):
        BaseOficial([ATIVIDADE_VALIDA], com_7)


def test_recusa_consulta_a_campo_que_nao_existe():
    base = BaseOficial([ATIVIDADE_VALIDA], LEGENDA_VALIDA)

    with pytest.raises(ErroBaseOficial, match="campo"):
        base.valores_distintos("inventado")
