"""
Etapa A — recuperação de atividades oficiais candidatas.

Estratégia: busca lexical ponderada (estilo BM25 simplificado) sobre os
radicais das palavras, reaproveitando a normalização/stemming do protótipo
`Chatbot.html`. Diferenças em relação ao protótipo:

- cada palavra da descrição pesa pelo quanto ela é rara na base (IDF):
  "consignado" distingue muito mais do que "cliente" ou "consulta";
- só `atividade`, `produto` e `subgrupo` entram na busca. `clientes`,
  `segmento` e `atendimento` descrevem o público, não o que foi feito, e
  aparecem em quase todo registro — só gerariam ruído;
- radicais casam por prefixo (mín. 4 letras), porque o stemming leve nem
  sempre reduz variações ao mesmo radical ("emprestimo" x "emprest").

Não há embeddings: a base tem ~800 registros curtos e o LLM já faz a
comparação semântica na etapa B. Qualquer outra estratégia pode entrar
implementando o protocolo `Recuperador`.
"""

import math
from dataclasses import dataclass
from typing import Protocol

from backend.dados import Atividade, BaseOficial

from .modelos import Candidato
from .texto import palavras, radicais

# Peso de cada campo pesquisado. Atividade e produto definem o registro
# (a chave única da base é o par atividade + produto); subgrupo só ajuda.
PESOS_CAMPOS = {"atividade": 2.0, "produto": 2.0, "subgrupo": 1.0}

MIN_PREFIXO = 4
LIMITE_PADRAO = 10


class Recuperador(Protocol):
    def buscar(self, texto: str, limite: int = LIMITE_PADRAO) -> list[Candidato]: ...


def radicais_casam(consulta: str, documento: str) -> bool:
    if consulta == documento:
        return True
    menor = min(len(consulta), len(documento))
    return menor >= MIN_PREFIXO and (
        documento.startswith(consulta) or consulta.startswith(documento)
    )


@dataclass(frozen=True)
class _Indexado:
    atividade: Atividade
    radicais_por_campo: dict[str, frozenset[str]]


class RecuperadorLexical:
    def __init__(self, base: BaseOficial):
        self._indice = [
            _Indexado(
                atividade=a,
                radicais_por_campo={
                    campo: frozenset(radicais(getattr(a, campo)))
                    for campo in PESOS_CAMPOS
                },
            )
            for a in base.listar_atividades()
        ]
        self._vocabulario = frozenset(
            r for item in self._indice for rs in item.radicais_por_campo.values() for r in rs
        )

    def radicais_conhecidos(self, texto: str) -> list[str]:
        """Radicais da descrição que casam com algo da base."""
        return [
            r for r in radicais(texto)
            if any(radicais_casam(r, v) for v in self._vocabulario)
        ]

    def _peso_no_registro(self, radical_consulta: str, item: _Indexado) -> float:
        return max(
            (
                PESOS_CAMPOS[campo]
                for campo, rs in item.radicais_por_campo.items()
                if any(radicais_casam(radical_consulta, r) for r in rs)
            ),
            default=0.0,
        )

    def buscar(self, texto: str, limite: int = LIMITE_PADRAO) -> list[Candidato]:
        consulta = self.radicais_conhecidos(texto)
        if not consulta:
            return []

        total = len(self._indice)
        pesos = {r: [self._peso_no_registro(r, item) for item in self._indice] for r in consulta}
        idf = {
            r: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for r, lista in pesos.items()
            for df in [sum(1 for p in lista if p > 0)]
        }

        # Mapeia radical → palavra original, para mostrar a evidência.
        palavra_de = {}
        for p in palavras(texto):
            for r in consulta:
                if r not in palavra_de and radicais(p) and radicais_casam(r, radicais(p)[0]):
                    palavra_de[r] = p

        pontuados = []
        for i, item in enumerate(self._indice):
            casados = [r for r in consulta if pesos[r][i] > 0]
            if not casados:
                continue
            pontuacao = sum(idf[r] * pesos[r][i] for r in casados)
            pontuados.append(
                Candidato(
                    atividade=item.atividade,
                    pontuacao=round(pontuacao, 4),
                    termos_casados=[palavra_de.get(r, r) for r in casados],
                )
            )

        pontuados.sort(key=lambda c: (-c.pontuacao, c.atividade.id))
        return pontuados[:limite]
