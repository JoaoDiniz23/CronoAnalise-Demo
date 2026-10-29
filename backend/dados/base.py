"""
Camada de acesso à base oficial do cliente.

Esta é a ÚNICA porta de entrada para os dados oficiais. Nenhum outro
componente (busca, LLM, interface) deve abrir os arquivos de `dados/`
diretamente — assim a regra de "o que é oficial" fica num lugar só.

A carga é validada de forma ruidosa: base inconsistente derruba o
carregamento com mensagem clara, em vez de deixar o sistema rodar com
dado corrompido e errar silenciosamente depois.
"""

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from .modelos import CAMPOS_MULTIVALOR, CAMPOS_SIMPLES, Atividade, separar

RAIZ = Path(__file__).resolve().parent.parent.parent
ARQUIVO_ATIVIDADES = RAIZ / "dados" / "atividades_padronizadas.json"
ARQUIVO_LEGENDA = RAIZ / "dados" / "legenda_folha_fisica.yaml"

# Domínio lido do molde oficial da folha (PDF vetorial em `conteúdos
# importantes/`, texto extraído do arquivo): a classificação vai de 1 a
# 20 e PULA O CÓDIGO 7. O código 8 é "C: Treinamento" e o 20 é
# "TNP: TNP do Consultor".
#
# O 7 não falta por descuido. O Guia de atualização (seção 2.1) registra
# a razão: "A numeração pula de 6 para 8 justamente para o 7 não ser
# confundido com o 1 na leitura da folha." O mesmo vale para a coluna
# Local da Atividade.
#
# Esta constante é a guarda da regra: se alguém editar a legenda e
# reintroduzir o 7 ou remover o 8, a carga falha na hora.
CODIGOS_CLASSIFICACAO_OFICIAIS = frozenset(set(range(1, 21)) - {7})


class ErroBaseOficial(Exception):
    """Base oficial ausente, incompleta ou inconsistente."""


class BaseOficial:
    """Atividades oficiais + legendas da folha física, prontas para consulta."""

    def __init__(self, atividades_brutas: list[dict], legenda_bruta: dict):
        self.atividades = self._validar_atividades(atividades_brutas)
        self._por_id = {a.id: a for a in self.atividades}

        legenda_bruta = legenda_bruta or {}
        self.classificacao: dict[int, str] = self._validar_classificacao(
            legenda_bruta.get("classificacao")
        )
        self.local_da_atividade: dict[int, str] = legenda_bruta.get(
            "local_da_atividade"
        ) or {}
        self.forma_de_atendimento: dict[int, str] = legenda_bruta.get(
            "forma_de_atendimento"
        ) or {}
        self.clientes_legenda: dict[int, str] = legenda_bruta.get("clientes") or {}
        # Segmento é preenchido com SIGLA, não com número — por isso a
        # chave aqui é str. Três siglas ("Mei", "B1", "B2") aparecem no
        # molde sem descrição e ficam com valor None, sem invenção.
        # Isto NÃO é um DE-PARA para os valores do campo `segmento` da
        # base de atividades: essa correspondência não foi confirmada.
        self.segmento_legenda: dict[str, str | None] | None = legenda_bruta.get(
            "segmento"
        )

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------

    @staticmethod
    def _validar_atividades(brutas: list[dict]) -> list[Atividade]:
        if not brutas:
            raise ErroBaseOficial("a base oficial de atividades está vazia")

        try:
            atividades = [Atividade(**bruta) for bruta in brutas]
        except (ValidationError, TypeError) as erro:
            raise ErroBaseOficial(
                f"registro inválido na base oficial de atividades: {erro}"
            ) from erro

        ids = [a.id for a in atividades]
        if len(set(ids)) != len(ids):
            repetidos = sorted({i for i in ids if ids.count(i) > 1})
            raise ErroBaseOficial(
                f"a base oficial tem id repetido: {repetidos}"
            )

        chaves = [(a.atividade, a.produto) for a in atividades]
        if len(set(chaves)) != len(chaves):
            repetidas = sorted({c for c in chaves if chaves.count(c) > 1})
            raise ErroBaseOficial(
                "a base oficial tem o par (atividade, produto) repetido: "
                f"{repetidas}"
            )

        return atividades

    @staticmethod
    def _validar_classificacao(bruta: dict | None) -> dict[int, str]:
        if not bruta:
            raise ErroBaseOficial(
                "a legenda de classificação oficial está ausente ou vazia"
            )

        codigos = set(bruta)
        if codigos != set(CODIGOS_CLASSIFICACAO_OFICIAIS):
            faltando = sorted(CODIGOS_CLASSIFICACAO_OFICIAIS - codigos)
            sobrando = sorted(codigos - CODIGOS_CLASSIFICACAO_OFICIAIS)
            raise ErroBaseOficial(
                "a legenda de classificação divergiu do molde oficial "
                "(1 a 20, sem o código 7). "
                f"Faltando: {faltando or 'nada'}. Inesperados: {sobrando or 'nada'}."
            )

        return dict(bruta)

    # ------------------------------------------------------------------
    # Consulta às atividades
    # ------------------------------------------------------------------

    def listar_atividades(self) -> list[Atividade]:
        return list(self.atividades)

    def atividade_por_id(self, id_atividade: int) -> Atividade | None:
        return self._por_id.get(id_atividade)

    def atividade_existe(self, id_atividade: int) -> bool:
        return id_atividade in self._por_id

    def valores_distintos(self, campo: str) -> list[str]:
        """Valores distintos de um campo, ordenados. Em campo multivalor,
        devolve os itens individuais, não as combinações."""
        if campo in CAMPOS_MULTIVALOR:
            valores = {
                item
                for atividade in self.atividades
                for item in separar(getattr(atividade, campo))
            }
        elif campo in CAMPOS_SIMPLES:
            valores = {getattr(atividade, campo) for atividade in self.atividades}
        else:
            permitidos = ", ".join(CAMPOS_SIMPLES + CAMPOS_MULTIVALOR)
            raise ErroBaseOficial(
                f"campo '{campo}' não existe na base oficial. "
                f"Campos disponíveis: {permitidos}."
            )
        return sorted(valores)

    # ------------------------------------------------------------------
    # Consulta às legendas oficiais
    # ------------------------------------------------------------------

    def codigos_classificacao(self) -> list[int]:
        return sorted(self.classificacao)

    def codigo_classificacao_existe(self, codigo: int) -> bool:
        return codigo in self.classificacao

    def descricao_classificacao(self, codigo: int) -> str | None:
        return self.classificacao.get(codigo)


def carregar_base_oficial(
    arquivo_atividades: Path | None = None,
    arquivo_legenda: Path | None = None,
) -> BaseOficial:
    """Carrega a base oficial dos arquivos de `dados/`."""
    atividades = _ler_json(arquivo_atividades or ARQUIVO_ATIVIDADES)
    legenda = _ler_yaml(arquivo_legenda or ARQUIVO_LEGENDA)
    return BaseOficial(atividades, legenda)


def _ler_json(caminho: Path) -> list[dict]:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError as erro:
        raise ErroBaseOficial(
            f"arquivo da base oficial não encontrado: {caminho}"
        ) from erro
    except json.JSONDecodeError as erro:
        raise ErroBaseOficial(
            f"arquivo da base oficial não é JSON válido ({caminho}): {erro}"
        ) from erro


def _ler_yaml(caminho: Path) -> dict:
    try:
        return yaml.safe_load(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError as erro:
        raise ErroBaseOficial(
            f"arquivo da legenda oficial não encontrado: {caminho}"
        ) from erro
    except yaml.YAMLError as erro:
        raise ErroBaseOficial(
            f"arquivo da legenda oficial não é YAML válido ({caminho}): {erro}"
        ) from erro
