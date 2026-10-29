"""
Testes contra o LLM REAL (Claude) — fora da suíte principal.

Só rodam com RODAR_TESTES_LLM_REAL=1 e a chave do provedor configurada; caso
contrário ficam como "skipped". Cada caso faz no máximo uma chamada.

    set RODAR_TESTES_LLM_REAL=1
    .venv\\Scripts\\python.exe -m pytest tests\\test_busca_llm_real.py -v

O que é exigido aqui é a segurança, não a perfeição: o modelo pode ser
conservador (responder "ambigua"/"sem_correspondencia" num caso que tinha
resposta), mas não pode escolher uma atividade errada nem devolver algo
que a validação recuse. A qualidade é medida com `scripts/avaliar_busca.py --llm`.
"""

import os
import sys
from pathlib import Path

import pytest

from backend.busca import StatusBusca, criar_buscador
from backend.dados import carregar_base_oficial

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from avaliar_busca import carregar_casos  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("RODAR_TESTES_LLM_REAL") != "1",
    reason="testes com o LLM real: defina RODAR_TESTES_LLM_REAL=1",
)

_BASE = carregar_base_oficial()
_CASOS = carregar_casos(_BASE)


@pytest.fixture(scope="module")
def buscador():
    return criar_buscador(_BASE)


def _com_limitacao(caso):
    """Caso com `limitacao_conhecida` nos dados: falha esperada e visível
    (xfail), não some da suíte nem a derruba."""
    motivo = caso.get("limitacao_conhecida")
    return pytest.param(caso, marks=pytest.mark.xfail(reason=motivo, strict=False)) if motivo else caso


@pytest.mark.parametrize(
    "caso", [_com_limitacao(c) for c in _CASOS], ids=[c["texto"][:40] for c in _CASOS]
)
def test_caso_real(buscador, caso):
    resultado = buscador.buscar(caso["texto"])

    if resultado.status == StatusBusca.LLM_INDISPONIVEL:
        pytest.skip(f"LLM indisponível: {resultado.erro.tipo} — {resultado.erro.mensagem}")

    assert resultado.status != StatusBusca.RESPOSTA_INVALIDA, resultado.erro

    if resultado.status == StatusBusca.ENCONTRADA:
        assert caso["esperado"] == "encontrada", (
            f"escolheu #{resultado.atividade.id} para um caso sem resposta certa"
        )
        assert resultado.atividade.id in caso["ids_aceitos"], (
            f"escolheu #{resultado.atividade.id} {resultado.atividade.atividade} | "
            f"{resultado.atividade.produto}; aceitas: {caso['aceitas']}"
        )
