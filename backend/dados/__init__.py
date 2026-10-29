"""
Base oficial do cliente — fonte de verdade das atividades.

Uso pelos demais componentes (busca/LLM, interface):

    from backend.dados import carregar_base_oficial

    base = carregar_base_oficial()

    base.listar_atividades()              # todas as atividades oficiais
    base.atividade_por_id(42)             # uma atividade (None se não existe)
    base.atividade_existe(42)             # bool
    base.valores_distintos("segmento")    # valores possíveis de um campo

    base.codigos_classificacao()          # [1..6, 8..20] (nao existe o 7)
    base.codigo_classificacao_existe(8)   # bool
    base.descricao_classificacao(8)       # "C: Treinamento"

    base.local_da_atividade               # {1..6, 8: str}
    base.forma_de_atendimento             # {1..6: str}
    base.clientes_legenda                 # {1..5: str}
    base.segmento_legenda                 # {sigla: str | None} (14 siglas)

Nenhum componente deve ler os arquivos de `dados/` diretamente.
"""

from .base import (
    CODIGOS_CLASSIFICACAO_OFICIAIS,
    BaseOficial,
    ErroBaseOficial,
    carregar_base_oficial,
)
from .modelos import Atividade

__all__ = [
    "Atividade",
    "BaseOficial",
    "ErroBaseOficial",
    "CODIGOS_CLASSIFICACAO_OFICIAIS",
    "carregar_base_oficial",
]
