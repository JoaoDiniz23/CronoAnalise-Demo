"""
Orquestração: roda todas as regras e junta os apontamentos.

O motor não tem lógica de validação própria — ele só chama as regras, na
ordem do registro, e concatena o que elas devolvem. Regra nova é uma
função nova em `regras.py` mais uma linha no registro; nada aqui muda.
"""

from backend.dados import BaseOficial

from . import regras
from .modelos import Conjunto, Folha
from .resultado import ResultadoValidacao


def validar_folha(folha: Folha, base: BaseOficial) -> ResultadoValidacao:
    """Valida uma folha isolada.

    Não avalia `soma_8h` nem `soma_por_mapeado`: as duas dependem do
    conjunto de folhas do mesmo mapeado no dia. Para elas, use
    `validar_conjunto`.
    """
    pontos = [p for regra in regras.REGRAS_DA_FOLHA for p in regra(folha, base)]
    return ResultadoValidacao(
        pontos_para_revisar=pontos,
        regras_aplicadas=list(regras.REGRAS_DO_CATALOGO_APLICADAS),
        regras_pendentes=sorted(regras.REGRAS_PENDENTES),
    )


def validar_regras_do_conjunto(
    conjunto: Conjunto, base: BaseOficial
) -> ResultadoValidacao:
    """SÓ as regras que dependem do dia inteiro do mapeado.

    Não roda nenhuma regra de folha. Existe para quem já validou cada
    folha individualmente e precisa completar com `soma_8h` e
    `soma_por_mapeado` — sem reexecutar (e sem duplicar) tudo o que já
    foi apontado folha a folha.

    É o que `backend/analise/` usa: validar cada ficha uma vez, amarrar
    cada ponto à ficha de origem, e só então avaliar o conjunto.
    """
    pontos = [p for regra in regras.REGRAS_DO_CONJUNTO for p in regra(conjunto, base)]
    return ResultadoValidacao(
        pontos_para_revisar=pontos,
        regras_aplicadas=[r.__name__ for r in regras.REGRAS_DO_CONJUNTO],
        regras_pendentes=sorted(regras.REGRAS_PENDENTES),
    )


def validar_conjunto(conjunto: Conjunto, base: BaseOficial) -> ResultadoValidacao:
    """Valida todas as folhas do conjunto e mais as regras que só fazem
    sentido sobre o dia inteiro do mapeado.

    Devolve os pontos num bolo só, sem dizer de qual folha veio cada um.
    Para um relatório que precise disso, use `validar_folha` por folha
    mais `validar_regras_do_conjunto`.
    """
    pontos = [
        p
        for folha in conjunto.folhas
        for regra in regras.REGRAS_DA_FOLHA
        for p in regra(folha, base)
    ]
    do_conjunto = validar_regras_do_conjunto(conjunto, base)
    pontos += do_conjunto.pontos_para_revisar

    aplicadas = list(regras.REGRAS_DO_CATALOGO_APLICADAS) + list(
        do_conjunto.regras_aplicadas
    )
    return ResultadoValidacao(
        pontos_para_revisar=pontos,
        regras_aplicadas=aplicadas,
        regras_pendentes=sorted(regras.REGRAS_PENDENTES),
    )
