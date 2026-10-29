"""
O que o motor devolve: uma lista de pontos para revisar.

Vocabulário deliberado. O produto **não certifica folha** (CLAUDE.md,
objetivo do MVP, módulo 3): ele aponta o que merece uma segunda olhada.
Por isso não existe aqui nenhum campo chamado `valida`, `aprovada` ou
`ok` — o mais longe que o resultado vai é dizer que *ele* não encontrou
nada, que é uma afirmação sobre o sistema, não sobre a folha.
"""

from enum import Enum

from pydantic import BaseModel


class TipoPonto(str, Enum):
    """As três categorias do PRD, seção 8, na ordem de gravidade."""

    # Regra objetivamente infringida pelo que está escrito na folha.
    ERRO = "erro"
    # A leitura não teve segurança. Não é erro do consultor: é limite do
    # sistema. Nunca vira valor assumido nem reprovação.
    CONFIRMAR = "confirmar"
    # Merece atenção, mas não é erro objetivo.
    ALERTA = "alerta"


class PontoParaRevisar(BaseModel):
    """Uma coisa para o consultor olhar de novo.

    Responde as quatro perguntas do PRD, seção 8: o que é o problema
    (`mensagem`), onde está (`linha`/`campo`) e qual regra o motivou
    (`regra`).
    """

    model_config = {"frozen": True}

    regra: str
    tipo: TipoPonto
    mensagem: str
    # Ausentes quando o ponto é da folha inteira ou do cabeçalho.
    linha: int | None = None
    campo: str | None = None


class ResultadoValidacao(BaseModel):
    """Saída do motor.

    ATENÇÃO — leia antes de usar isto numa tela: uma lista vazia de
    pontos significa apenas que **nenhuma das regras implementadas
    encontrou problema**. Isso NUNCA deve ser apresentado ao consultor
    como "folha correta", "folha validada" ou "folha aprovada". Parte
    das regras do catálogo não está implementada (ver
    `regras_pendentes`), e nenhuma regra cobre se o que foi cronometrado
    corresponde ao que de fato aconteceu na loja.
    """

    model_config = {"frozen": True}

    pontos_para_revisar: list[PontoParaRevisar] = []
    # Regras do catálogo que efetivamente rodaram nesta validação.
    regras_aplicadas: list[str] = []
    # Regras do catálogo que NÃO rodaram, por falta de definição oficial.
    regras_pendentes: list[str] = []

    @property
    def sem_pontos_para_revisar(self) -> bool:
        """O motor não encontrou nada. Não quer dizer que a folha está
        correta — ver a docstring da classe."""
        return not self.pontos_para_revisar

    def por_tipo(self, tipo: TipoPonto) -> list[PontoParaRevisar]:
        return [p for p in self.pontos_para_revisar if p.tipo is tipo]
