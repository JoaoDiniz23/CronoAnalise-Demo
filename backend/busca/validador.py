"""
Validação da resposta do LLM — a barreira contra atividade inventada.

Nada que o LLM devolve é aceito sem passar por aqui. A validação é
estrita de propósito:

- JSON inválido, vazio, com campo faltando ou com campo a mais → recusa;
- ID como string ("42") ou booleano → recusa (sem conversão silenciosa);
- combinação incoerente (ex.: "encontrada" sem ID) → recusa;
- ID que não estava entre os candidatos → recusa, mesmo que exista na base;
- ID que não existe na base oficial → recusa.

Coerência com a comparação do próprio modelo (29/09/2026): antes de
decidir, o LLM compara os registros mais parecidos (`comparacao`, ver
`interpretador.SCHEMA_RESPOSTA`). Se a comparação marca o próprio
escolhido como OUTRO objeto, o raciocínio contradiz a decisão: a resposta
vira "ambigua" (ou "nenhuma", se não sobrar alternativa) e o consultor
escolhe, em vez de receber um palpite. Outros registros com o mesmo
objeto não contam como contradição — "abriu uma conta corrente" tem
Abertura, Aprovação e Formalização sobre o mesmo objeto, e o verbo decide.
Esses campos de raciocínio são tolerantes (faltando ou incompletos não
recusam a resposta); os da decisão continuam estritos.

Os dados devolvidos saem de `base.atividade_por_id`, nunca do texto do LLM.
"""

import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.dados import Atividade, BaseOficial

from .modelos import Candidato


class RespostaInvalida(Exception):
    """A resposta do LLM foi recusada. A mensagem explica o motivo."""

    def __init__(self, motivo: str, resposta_bruta: str):
        super().__init__(motivo)
        self.motivo = motivo
        self.resposta_bruta = resposta_bruta


class _AcaoObservada(BaseModel):
    model_config = ConfigDict(extra="ignore")

    verbo: str = ""
    objeto: str = ""
    produto: str = ""


class _Comparado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    mesmo_objeto: bool | None = None


class _RespostaLLM(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Raciocínio (tolerante): o que foi feito e a comparação dos parecidos.
    acao_observada: _AcaoObservada | None = None
    comparacao: list[_Comparado] = []
    # Decisão (estrita).
    decisao: Literal["encontrada", "ambigua", "nenhuma"]
    id_atividade: int | None
    ids_possiveis: list[int]
    justificativa: str = Field(min_length=1)
    # Opcional: TNP do próprio consultor (código 20, fora da base).
    tnp_do_consultor: bool = False


# Mesmo máximo de opções que o prompt pede em "ambigua".
MAX_ALTERNATIVAS = 5

# Justificativa quando a decisão contradiz a comparação do próprio modelo.
JUSTIFICATIVA_INCOERENTE = (
    "a busca inteligente não confirmou uma única atividade; escolha a que foi feita"
)


@dataclass(frozen=True)
class DecisaoValidada:
    decisao: Literal["encontrada", "ambigua", "nenhuma"]
    justificativa: str
    atividade: Atividade | None = None
    alternativas: list[Atividade] = field(default_factory=list)
    tnp_do_consultor: bool = False
    # Para o log: a ação que o modelo leu e se a checagem de coerência
    # mudou a decisão dele.
    acao_observada: str = ""
    ajustada_pela_comparacao: bool = False


def remover_cercas_markdown(texto: str) -> str:
    """Remove ```json ... ``` se o modelo as incluir."""
    texto = texto.strip()
    if texto.startswith("```"):
        linhas = texto.splitlines()[1:]
        if linhas and linhas[-1].strip().startswith("```"):
            linhas = linhas[:-1]
        texto = "\n".join(linhas).strip()
    return texto


def validar_resposta(
    bruta: str, candidatos: list[Candidato], base: BaseOficial
) -> DecisaoValidada:
    texto = remover_cercas_markdown(bruta or "")
    if not texto:
        raise RespostaInvalida("resposta vazia", bruta)

    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise RespostaInvalida(f"JSON inválido: {erro}", bruta) from erro

    try:
        resposta = _RespostaLLM.model_validate(dados)
    except ValidationError as erro:
        problemas = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'resposta'}: {e['msg']}"
            for e in erro.errors()
        )
        raise RespostaInvalida(f"estrutura inválida ({problemas})", bruta) from erro

    ids_candidatos = {c.atividade.id for c in candidatos}
    a = resposta.acao_observada
    acao = f"verbo={a.verbo} objeto={a.objeto} produto={a.produto}" if a else ""

    def oficial(id_atividade: int) -> Atividade:
        if id_atividade not in ids_candidatos:
            enviados = sorted(ids_candidatos)
            resumo = enviados if len(enviados) <= 20 else f"{len(enviados)} IDs"
            raise RespostaInvalida(
                f"ID {id_atividade} não estava entre os candidatos enviados ({resumo})",
                bruta,
            )
        if not base.atividade_existe(id_atividade):
            raise RespostaInvalida(
                f"ID {id_atividade} não existe na base oficial", bruta
            )
        return base.atividade_por_id(id_atividade)

    if resposta.decisao == "encontrada":
        if resposta.id_atividade is None:
            raise RespostaInvalida("decisão 'encontrada' sem id_atividade", bruta)
        if resposta.ids_possiveis:
            raise RespostaInvalida(
                "decisão 'encontrada' não pode ter ids_possiveis", bruta
            )
        atividade = oficial(resposta.id_atividade)
        ids = _contradicoes(resposta, ids_candidatos, base)
        if ids is not None:
            return DecisaoValidada(
                decisao="ambigua" if len(ids) >= 2 else "nenhuma",
                justificativa=JUSTIFICATIVA_INCOERENTE,
                alternativas=[oficial(i) for i in ids] if len(ids) >= 2 else [],
                acao_observada=acao,
                ajustada_pela_comparacao=True,
            )
        return DecisaoValidada(
            decisao="encontrada",
            justificativa=resposta.justificativa,
            atividade=atividade,
            # Só vale sobre um registro de Tempo não produtivo: o LLM não
            # consegue virar "20" uma venda, por exemplo.
            tnp_do_consultor=resposta.tnp_do_consultor
            and atividade.subgrupo.startswith("Tempo não produtivo"),
            acao_observada=acao,
        )

    if resposta.id_atividade is not None:
        raise RespostaInvalida(
            f"decisão '{resposta.decisao}' não pode ter id_atividade", bruta
        )

    if resposta.decisao == "ambigua":
        ids = list(dict.fromkeys(resposta.ids_possiveis))
        if len(ids) < 2:
            raise RespostaInvalida(
                "decisão 'ambigua' precisa de pelo menos 2 ids_possiveis distintos",
                bruta,
            )
        return DecisaoValidada(
            decisao="ambigua",
            justificativa=resposta.justificativa,
            alternativas=[oficial(i) for i in ids],
            acao_observada=acao,
        )

    if resposta.ids_possiveis:
        raise RespostaInvalida("decisão 'nenhuma' não pode ter ids_possiveis", bruta)
    return DecisaoValidada(
        decisao="nenhuma", justificativa=resposta.justificativa, acao_observada=acao
    )


def _contradicoes(
    resposta: _RespostaLLM, ids_candidatos: set[int], base: BaseOficial
) -> list[int] | None:
    """None se a comparação não contradiz "encontrada" (ou não diz nada
    sobre o escolhido). Se ela marca o escolhido como outro objeto, os IDs
    que o consultor deve ver: os marcados como o mesmo objeto primeiro,
    depois o escolhido. IDs fora do catálogo ou da base são ignorados."""
    escolhido = resposta.id_atividade
    marcas: dict[int, bool] = {}
    for c in resposta.comparacao:
        if (
            c.id is not None
            and c.mesmo_objeto is not None
            and c.id in ids_candidatos
            and base.atividade_existe(c.id)
        ):
            marcas.setdefault(c.id, c.mesmo_objeto)
    if marcas.get(escolhido) is not False:
        return None
    outros_iguais = [i for i, igual in marcas.items() if igual and i != escolhido]
    if outros_iguais:
        return (outros_iguais + [escolhido])[:MAX_ALTERNATIVAS]
    return ([escolhido] + [i for i in marcas if i != escolhido])[:MAX_ALTERNATIVAS]
