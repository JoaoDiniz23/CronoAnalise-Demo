"""Verbos de relato viram enchimento, mas nunca apagam palavra da base."""

from backend.busca.texto import STOPWORDS, normalizar
from backend.busca.servico import correspondencia_por_nome
from backend.dados import carregar_base_oficial

RELATO = {
    "fala", "falar", "falando", "falou", "conversa", "conversar", "conversando",
    "conversou", "comentar", "comentando", "comentou", "dizer", "dizendo", "disse",
}


def test_nenhuma_stopword_e_palavra_de_nome_da_base():
    base = carregar_base_oficial()
    nomes = set()
    for a in base.listar_atividades():
        nomes |= set(normalizar(f"{a.atividade} {a.produto}").split())
    assert RELATO <= STOPWORDS
    assert not (RELATO & nomes)


def test_relato_de_conversa_sobre_produto_lista_na_hora():
    base = carregar_base_oficial()
    assert correspondencia_por_nome("funcionario falando sobre cartão de crédito", base) == (
        correspondencia_por_nome("cartão de crédito", base)
    )
    # negação continua indo para o LLM
    assert correspondencia_por_nome("disse que não quer o saque", base) == []
