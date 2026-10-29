"""
Como uma folha de coleta JÁ LIDA é representada.

Princípio desta camada: estes modelos não sabem de onde o dado veio.
Podem ter sido produzidos por foto + OCR, por um modelo multimodal, ou
digitados à mão por alguém conferindo a folha. O motor de regras valida
o mesmo objeto nos três casos — é isso que permite testar toda a
validação sem imagem nenhuma.

Duas decisões sustentam isso:

1. **Toda célula guarda TEXTO CRU.** Nada é convertido para inteiro na
   entrada. Se a coluna Clientes (numérica) contém "PF", o modelo
   precisa conseguir representar isso — é justamente esse o erro que as
   regras de domínio existem para apontar. Converter na leitura
   destruiria o achado.

2. **"Vazia" e "ilegível" são estados diferentes, nunca colapsados.**
   Campo em branco é erro do consultor (Manual, p. 43). Célula ilegível
   é limite da leitura: vira pedido de confirmação, nunca erro e nunca
   valor assumido.
"""

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel


class EstadoLeitura(str, Enum):
    """Em que situação a célula chegou da leitura."""

    # Havia algo escrito e foi lido. O texto está em `valor`.
    PREENCHIDA = "preenchida"
    # A célula está em branco na folha.
    VAZIA = "vazia"
    # Havia algo escrito, mas não foi possível ler com segurança.
    ILEGIVEL = "ilegivel"


class Celula(BaseModel):
    """Uma célula da folha, como foi lida."""

    model_config = {"frozen": True}

    valor: str | None = None
    estado: EstadoLeitura

    @classmethod
    def lida(cls, texto: str) -> "Celula":
        """Célula com conteúdo. Texto só com espaço conta como vazia —
        o consultor não escreveu nada ali."""
        if texto is None or not texto.strip():
            return cls.vazia()
        return cls(valor=texto, estado=EstadoLeitura.PREENCHIDA)

    @classmethod
    def vazia(cls) -> "Celula":
        return cls(valor=None, estado=EstadoLeitura.VAZIA)

    @classmethod
    def ilegivel(cls) -> "Celula":
        return cls(valor=None, estado=EstadoLeitura.ILEGIVEL)

    @property
    def tem_valor(self) -> bool:
        return self.estado is EstadoLeitura.PREENCHIDA

    @property
    def texto(self) -> str:
        """Conteúdo sem espaço nas pontas. Vazio se não há valor."""
        return (self.valor or "").strip()


class Cabecalho(BaseModel):
    """Faixa superior da folha. Uma ocorrência por folha."""

    model_config = {"frozen": True}

    CAMPOS: ClassVar[tuple[str, ...]] = (
        "data", "uniorg", "loja", "nome", "matricula",
        "cargo", "id_responsavel", "numero_folha",
    )

    data: Celula
    uniorg: Celula
    loja: Celula
    nome: Celula
    matricula: Celula
    cargo: Celula
    id_responsavel: Celula
    numero_folha: Celula

    def celulas(self) -> list[tuple[str, Celula]]:
        return [(campo, getattr(self, campo)) for campo in self.CAMPOS]


class Linha(BaseModel):
    """Uma das 15 linhas do corpo da folha.

    A ordem de `CAMPOS` é a ordem impressa das colunas, da esquerda para
    a direita — assim os apontamentos saem na ordem em que o consultor
    lê a folha.
    """

    model_config = {"frozen": True}

    CAMPOS: ClassVar[tuple[str, ...]] = (
        "num_processo", "detalhamento", "produto", "segmento", "agenda_certo",
        "classificacao", "local", "atendimento", "clientes", "venda_concluida",
        "hora", "minutos", "segundos", "quantidade", "ocorrencia",
    )

    numero: int

    num_processo: Celula
    detalhamento: Celula
    produto: Celula
    segmento: Celula
    agenda_certo: Celula
    classificacao: Celula
    local: Celula
    atendimento: Celula
    clientes: Celula
    venda_concluida: Celula
    hora: Celula
    minutos: Celula
    segundos: Celula
    quantidade: Celula
    ocorrencia: Celula

    def celulas(self) -> list[tuple[str, Celula]]:
        return [(campo, getattr(self, campo)) for campo in self.CAMPOS]

    @property
    def em_uso(self) -> bool:
        """A linha foi usada se qualquer célula não está vazia.

        Uma folha de 15 linhas quase nunca é preenchida inteira: linha
        não usada não é erro. Linha usada pela metade é — e quem aponta
        isso é `linha_sem_brancos`.
        """
        return any(c.estado is not EstadoLeitura.VAZIA for _, c in self.celulas())


class Folha(BaseModel):
    """Uma folha de coleta lida."""

    model_config = {"frozen": True}

    cabecalho: Cabecalho
    linhas: list[Linha]

    @property
    def linhas_em_uso(self) -> list[Linha]:
        return [linha for linha in self.linhas if linha.em_uso]


class Conjunto(BaseModel):
    """Várias folhas que deveriam ser do mesmo colaborador mapeado.

    Existe porque duas regras do catálogo (`soma_8h` e
    `soma_por_mapeado`) não são avaliáveis numa folha isolada: o total
    de 8 horas é do dia do mapeado, distribuído por quantas folhas
    forem necessárias.
    """

    model_config = {"frozen": True}

    folhas: list[Folha]
