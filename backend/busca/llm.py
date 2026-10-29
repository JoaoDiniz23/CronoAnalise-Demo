"""
Contrato do LLM da busca — protocolo `ClienteLLM` e erros tipados.

O resto da busca só conhece `ClienteLLM.gerar(prompt, schema) -> str` e as
exceções `ErroLLM`. O cliente real é o Claude (`llm_anthropic.py`); os
testes usam um cliente falso, sem rede. (O cliente Gemini saiu em
23/09/2026: o chatbot roda só com o Claude, crédito pré-pago.)

Política de retry, aplicada pelo cliente: no máximo `MAX_TENTATIVAS`, com
`BACKOFF_S` entre elas, só para falha TRANSITÓRIA do provedor (5xx,
sobrecarga, timeout, rede). Quota/crédito (429) e erro de chave sobem na 1ª
tentativa — repetir sozinho multiplicaria consumo ou não resolveria nada.
Quem chama recebe um erro tipado e decide (a interface oferece os
candidatos da busca).
"""

import time
from dataclasses import dataclass
from typing import Protocol

# No máximo 2 tentativas TOTAIS (a original + 1 retry), com um backoff curto
# entre elas. Política fixa, não configuração de operador.
MAX_TENTATIVAS = 2
BACKOFF_S = 3.0


class ErroLLM(Exception):
    """Falha ao consultar o LLM. `tipo` vai para o resultado da busca."""

    tipo = "erro_llm"


class ErroChaveAusente(ErroLLM):
    tipo = "chave_ausente"


class ErroChaveInvalida(ErroLLM):
    """Chave presente, mas recusada pelo provedor (401/403)."""

    tipo = "chave_invalida"


class ErroQuota(ErroLLM):
    """HTTP 429 ou crédito pré-pago esgotado — repetir sozinho não ajuda."""

    tipo = "quota_ou_limite"


class ErroTimeout(ErroLLM):
    tipo = "timeout"


class ErroApiIndisponivel(ErroLLM):
    """Falha de rede ou erro 5xx do provedor."""

    tipo = "api_indisponivel"


class ErroModeloIndisponivel(ErroLLM):
    """Modelo inexistente/não habilitado (404) ou sobrecarregado (503)."""

    tipo = "modelo_indisponivel"


class ClienteLLM(Protocol):
    modelo: str

    def gerar(self, prompt: str, schema: dict | None, sistema: str | None = None) -> str:
        """Devolve o texto bruto da resposta. `schema` descreve o JSON
        esperado (o cliente pode ignorá-lo: o pedido já o traz por extenso e
        o `validador` confere tudo). `sistema` é a parte
        fixa do pedido (regras + catálogo), que o provedor pode guardar em
        cache. Levanta `ErroLLM`."""
        ...


@dataclass(frozen=True)
class Consumo:
    """Tokens de uma chamada, para o log de custo. Nunca inventado: só
    existe quando o provedor devolveu a contagem na resposta."""

    tokens_entrada: int
    tokens_saida: int


def _dormir(segundos: float) -> None:
    """Isolado para os testes substituírem por um no-op (`monkeypatch`) e
    não esperar o backoff de verdade a cada caso de retry."""
    time.sleep(segundos)
