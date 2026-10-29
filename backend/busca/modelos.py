"""
Tipos públicos da busca de atividades — o contrato com a interface.

A interface (`frontend/busca.js`) só precisa conhecer `ResultadoBusca`. Regras de leitura:

- `status` diz o que aconteceu; só `encontrada` traz uma `atividade`.
- `atividade`, `alternativas` e `candidatos` são SEMPRE registros vindos da
  base oficial (`backend.dados`), nunca texto produzido pelo LLM.
- `justificativa` é texto livre do LLM: serve para explicar a escolha ao
  consultor, não é dado oficial e não deve ser gravado como tal.
- Nenhum campo aqui é código de classificação da folha. A relação
  subgrupo → código da legenda ainda não foi confirmada pelo cliente.
"""

from enum import Enum

from pydantic import BaseModel

from backend.dados import Atividade


class StatusBusca(str, Enum):
    # Uma atividade oficial foi identificada (pela busca ou pelo LLM).
    ENCONTRADA = "encontrada"
    # Mais de uma atividade oficial é plausível; ver `alternativas`.
    AMBIGUA = "ambigua"
    # Nenhuma atividade oficial corresponde ao que foi descrito.
    SEM_CORRESPONDENCIA = "sem_correspondencia"
    # Texto vazio ou sem nenhuma palavra que permita buscar.
    ENTRADA_INSUFICIENTE = "entrada_insuficiente"
    # O LLM não pôde ser consultado (chave, quota, timeout, rede...).
    # Os `candidatos` da busca continuam disponíveis para escolha manual.
    LLM_INDISPONIVEL = "llm_indisponivel"
    # O LLM respondeu, mas a resposta foi recusada pela validação
    # (JSON inválido, ID inexistente, ID fora dos candidatos...).
    # Os `candidatos` continuam disponíveis para escolha manual.
    RESPOSTA_INVALIDA = "resposta_invalida"


class Origem(str, Enum):
    # Resolvido só pela busca determinística, sem chamar o LLM.
    BUSCA = "busca"
    # Resolvido pelo LLM escolhendo entre os candidatos da busca.
    LLM = "llm"


class Candidato(BaseModel):
    """Atividade oficial recuperada pela busca, com a evidência lexical."""

    atividade: Atividade
    pontuacao: float
    # Palavras da descrição do consultor que casaram com esta atividade.
    termos_casados: list[str]


class DetalheErro(BaseModel):
    # Um de: chave_ausente, quota_ou_limite, timeout, api_indisponivel,
    # modelo_indisponivel, erro_llm, resposta_invalida.
    tipo: str
    mensagem: str


class ResultadoBusca(BaseModel):
    texto_original: str
    status: StatusBusca
    origem: Origem | None = None
    atividade: Atividade | None = None
    alternativas: list[Atividade] = []
    candidatos: list[Candidato] = []
    justificativa: str | None = None
    erro: DetalheErro | None = None
    modelo: str | None = None
    # Tempo parado do PRÓPRIO consultor: a folha usa o código 20 (TNP do
    # Consultor, Guia §1.4), que não existe na base — `atividade` é o
    # registro "Tempo não produtivo" e a tela troca só a Classificação.
    tnp_do_consultor: bool = False
    # Cota diária de LLM por pessoa (backend/acesso.py): se ESTA busca
    # gastou um uso, e quantos restam hoje. A tela avisa de 5 em 5.
    consumiu_llm: bool = False
    usos_llm_restantes: int | None = None
    limite_llm_dia: int | None = None
