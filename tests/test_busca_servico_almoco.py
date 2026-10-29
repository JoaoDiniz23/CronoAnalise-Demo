"""'Almoço' digitado sozinho: colaborador (Tempo não produtivo) e consultor."""

from backend.busca.servico import MENSAGEM_ALMOCO, criar_buscador
from backend.busca.modelos import StatusBusca


def test_almoco_sozinho_oferece_colaborador_primeiro_e_consultor():
    buscador = criar_buscador(cliente_llm=None)
    for texto in ("almoço", "Almoco"):
        r = buscador.buscar(texto)
        assert r.status == StatusBusca.AMBIGUA
        assert [a.atividade for a in r.alternativas] == ["Tempo não produtivo", "Almoço"]
        assert r.justificativa == MENSAGEM_ALMOCO
