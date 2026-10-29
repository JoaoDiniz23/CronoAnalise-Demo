"""
Validação da folha de coleta — dados estruturados → pontos para revisar.

Esta camada é **cega quanto à origem do dado**. Ela recebe uma `Folha`
já lida e não sabe (nem pode saber) se os valores vieram de foto + OCR,
de um modelo multimodal, ou de alguém digitando. É isso que permite
testar toda a validação sem imagem, e trocar a tecnologia de leitura
depois sem tocar em nenhuma regra.

    from backend.dados import carregar_base_oficial
    from backend.folha import Celula, Folha, validar_folha

    resultado = validar_folha(folha, carregar_base_oficial())
    for ponto in resultado.pontos_para_revisar:
        print(ponto.linha, ponto.campo, ponto.mensagem)

O resultado aponta o que revisar. Ele NUNCA diz que a folha está
correta — ver a docstring de `ResultadoValidacao`.

Os domínios (Classificação, Local, Forma de Atendimento, Clientes,
Segmento) vêm todos de `backend.dados.BaseOficial`. Nenhuma lista de
domínio é mantida aqui.
"""

from .modelos import Cabecalho, Celula, Conjunto, EstadoLeitura, Folha, Linha
from .motor import validar_conjunto, validar_folha, validar_regras_do_conjunto
from .regras import (
    CAMPOS_FORA_DO_ESCOPO,
    REGRAS_DO_CATALOGO_APLICADAS,
    REGRAS_PENDENTES,
    fora_do_escopo_funcional,
)
from .resultado import PontoParaRevisar, ResultadoValidacao, TipoPonto

__all__ = [
    "Cabecalho",
    "CAMPOS_FORA_DO_ESCOPO",
    "Celula",
    "Conjunto",
    "EstadoLeitura",
    "Folha",
    "Linha",
    "PontoParaRevisar",
    "REGRAS_DO_CATALOGO_APLICADAS",
    "REGRAS_PENDENTES",
    "ResultadoValidacao",
    "TipoPonto",
    "fora_do_escopo_funcional",
    "validar_conjunto",
    "validar_folha",
    "validar_regras_do_conjunto",
]
