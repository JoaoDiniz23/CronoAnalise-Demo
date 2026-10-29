"""
Busca de atividades oficiais a partir da descrição livre do consultor.

Uso (backend / interface):

    from backend.busca import criar_buscador

    buscador = criar_buscador()          # base oficial + busca lexical + LLM (Claude)
    resultado = buscador.buscar("atendeu cliente com dúvida do consignado")

    resultado.status        # encontrada | ambigua | sem_correspondencia |
                            # entrada_insuficiente | llm_indisponivel |
                            # resposta_invalida
    resultado.atividade     # Atividade oficial (só quando "encontrada")
    resultado.alternativas  # Atividades oficiais plausíveis (quando "ambigua")
    resultado.candidatos    # o que a busca lexical recuperou, com evidência

Ver `modelos.py` para o contrato completo e `servico.py` para o fluxo.
"""

from .llm import ClienteLLM, ErroLLM
from .llm_anthropic import ClienteClaude, criar_cliente_llm
from .modelos import Candidato, DetalheErro, Origem, ResultadoBusca, StatusBusca
from .recuperador import Recuperador, RecuperadorLexical
from .servico import BuscadorAtividades, criar_buscador

__all__ = [
    "BuscadorAtividades",
    "Candidato",
    "ClienteClaude",
    "criar_cliente_llm",
    "ClienteLLM",
    "DetalheErro",
    "ErroLLM",
    "Origem",
    "Recuperador",
    "RecuperadorLexical",
    "ResultadoBusca",
    "StatusBusca",
    "criar_buscador",
]
