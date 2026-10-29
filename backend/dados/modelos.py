"""
Modelos da base oficial de atividades do cliente.

Princípio desta camada: os arquivos em `dados/` são a fonte de verdade e
NÃO são alterados aqui. O modelo abaixo espelha fielmente os campos como
eles existem na fonte — inclusive os campos multivalor, que continuam
disponíveis no formato bruto (string separada por vírgula).

As listas (`clientes_lista` etc.) são leitura mecânica do valor bruto, não
interpretação: apenas separam por vírgula e removem espaços nas pontas.
Nenhuma correção de grafia, acentuação ou DE-PARA acontece aqui — isso
seria alterar dado oficial, e qualquer divergência encontrada deve ser
levada ao cliente, não corrigida no código.
"""

from pydantic import BaseModel, computed_field, field_validator

# Campos cujo valor oficial pode conter vários itens separados por vírgula.
CAMPOS_MULTIVALOR = ("clientes", "segmento", "atendimento")

# Campos de valor único.
CAMPOS_SIMPLES = ("atividade", "produto", "subgrupo", "classificacao")

CAMPOS_TEXTO = CAMPOS_SIMPLES + CAMPOS_MULTIVALOR


def separar(valor: str) -> list[str]:
    """Separa um campo multivalor. Verificado em 19/09/2026 sobre os 787
    registros: nenhum valor tem parênteses desbalanceados ou vírgula
    interna, então separar por vírgula é seguro nesta base."""
    return [parte.strip() for parte in valor.split(",") if parte.strip()]


class Atividade(BaseModel):
    """Uma linha da base oficial, fiel à fonte."""

    model_config = {"frozen": True}

    id: int
    atividade: str
    produto: str
    subgrupo: str
    clientes: str
    segmento: str
    atendimento: str
    classificacao: str

    @field_validator(*CAMPOS_TEXTO)
    @classmethod
    def _nao_pode_ser_vazio(cls, valor: str, info) -> str:
        if not valor or not valor.strip():
            raise ValueError(
                f"campo obrigatório '{info.field_name}' está vazio na base oficial"
            )
        return valor

    @computed_field
    @property
    def clientes_lista(self) -> list[str]:
        return separar(self.clientes)

    @computed_field
    @property
    def segmento_lista(self) -> list[str]:
        return separar(self.segmento)

    @computed_field
    @property
    def atendimento_lista(self) -> list[str]:
        return separar(self.atendimento)
