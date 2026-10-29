"""
Cliente Claude (Anthropic) para a busca de atividades — cumpre `ClienteLLM`.

Decisão de 22/09/2026 (usuário): Claude Haiku 4.5 com crédito PRÉ-PAGO na
Anthropic — custo máximo conhecido de antemão (crédito acabou = API para,
nunca cobra além). Único provedor desde 23/09/2026 (Gemini removido).

Configuração (variáveis de ambiente ou `.env` na raiz, nunca no código):
    ANTHROPIC_API_KEY     chave da API (obrigatória para chamar o Claude)
    ANTHROPIC_MODELO      padrão: claude-haiku-4-5-20251001
    ANTHROPIC_TIMEOUT_S   padrão: 20

Política de retry de `llm.MAX_TENTATIVAS`/`BACKOFF_S`: só
falha transitória (5xx, 529 "overloaded", timeout, rede) ganha nova
tentativa; 429 e erro de chave sobem na 1ª. O retry interno do SDK fica
desligado (`max_retries=0`) para não multiplicar tentativas por baixo.

O schema NÃO vai como saída estruturada nativa: o prompt já carrega o
schema por extenso e o `validador` confere tudo de novo, com mais rigor.
"""

import logging
import os

from dotenv import load_dotenv

from . import llm
from .llm import (
    Consumo,
    ErroApiIndisponivel,
    ErroChaveAusente,
    ErroChaveInvalida,
    ErroLLM,
    ErroModeloIndisponivel,
    ErroQuota,
    ErroTimeout,
)

logger = logging.getLogger(__name__)

MODELO_PADRAO = "claude-haiku-4-5-20251001"
TIMEOUT_PADRAO_S = 20.0
# A resposta é um JSON com a ação observada, a comparação de 2–3 registros
# e a decisão — medido em 29/09/2026: ~250–400 tokens. Cortar no meio vira
# JSON inválido (resposta recusada); o teto só segura um caso patológico.
MAX_TOKENS_SAIDA = 700


def ler_chave_anthropic() -> str:
    load_dotenv()
    chave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not chave:
        raise ErroChaveAusente(
            "ANTHROPIC_API_KEY não encontrada no ambiente nem no .env da raiz."
        )
    return chave


def traduzir_erro_anthropic(codigo: int, mensagem: str, modelo: str) -> ErroLLM:
    detalhe = f"{codigo}: {mensagem or 'sem mensagem'}"
    if codigo == 429:
        return ErroQuota(f"limite de requisições ou crédito da Anthropic atingido ({detalhe})")
    if codigo in (401, 403):
        return ErroChaveInvalida(f"chave da API recusada pela Anthropic ({detalhe})")
    if codigo == 404:
        return ErroModeloIndisponivel(f"modelo '{modelo}' não encontrado ({detalhe})")
    if codigo in (503, 529):
        return ErroModeloIndisponivel(f"modelo '{modelo}' sobrecarregado ({detalhe})")
    if codigo == 504:
        return ErroTimeout(f"a Anthropic excedeu o tempo de resposta ({detalhe})")
    if codigo >= 500:
        return ErroApiIndisponivel(f"erro no servidor da Anthropic ({detalhe})")
    # 400 inclui "crédito insuficiente" (saldo pré-pago zerado).
    if "credit" in (mensagem or "").lower():
        return ErroQuota(f"crédito pré-pago da Anthropic esgotado ({detalhe})")
    return ErroLLM(f"erro ao chamar a Anthropic ({detalhe})")


class ClienteClaude:
    def __init__(
        self,
        chave_api: str | None = None,
        modelo: str | None = None,
        timeout_s: float | None = None,
    ):
        load_dotenv()
        self._chave_api = chave_api
        self.modelo = modelo or os.environ.get("ANTHROPIC_MODELO", "").strip() or MODELO_PADRAO
        self.timeout_s = timeout_s or float(
            os.environ.get("ANTHROPIC_TIMEOUT_S", "") or TIMEOUT_PADRAO_S
        )
        self._cliente = None
        self.ultimo_consumo: Consumo | None = None

    def _sdk(self):
        # Criado só na primeira chamada: o backend sobe e a busca lexical
        # funciona mesmo sem chave configurada.
        if self._cliente is None:
            import anthropic

            self._cliente = anthropic.Anthropic(
                api_key=self._chave_api or ler_chave_anthropic(),
                timeout=self.timeout_s,
                max_retries=0,
            )
        return self._cliente

    def gerar(self, prompt: str, schema: dict | None, sistema: str | None = None) -> str:
        resposta = self._chamar_com_retry(prompt, sistema)
        uso = getattr(resposta, "usage", None)
        entrada = getattr(uso, "input_tokens", None)
        saida = getattr(uso, "output_tokens", None)
        self.ultimo_consumo = (
            Consumo(tokens_entrada=entrada, tokens_saida=saida)
            if entrada is not None and saida is not None
            else None
        )
        if self.ultimo_consumo is not None:
            logger.info(
                "busca de atividades: consumo modelo=%s tokens_entrada=%d tokens_saida=%d "
                "cache_lido=%s cache_gravado=%s",
                self.modelo, entrada, saida,
                getattr(uso, "cache_read_input_tokens", None),
                getattr(uso, "cache_creation_input_tokens", None),
            )
        return "".join(
            bloco.text for bloco in resposta.content if getattr(bloco, "type", "") == "text"
        )

    def _chamar_com_retry(self, prompt: str, sistema: str | None = None):
        import anthropic

        extra = {}
        if sistema:
            # Catálogo inteiro (~14 mil tokens), igual em toda busca: em cache,
            # as leituras seguintes custam ~10% (TTL de 5 min, renovado a cada uso).
            extra["system"] = [
                {"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}
            ]
        for tentativa in range(1, llm.MAX_TENTATIVAS + 1):
            ultima = tentativa == llm.MAX_TENTATIVAS
            try:
                return self._sdk().messages.create(
                    model=self.modelo,
                    max_tokens=MAX_TOKENS_SAIDA,
                    messages=[{"role": "user", "content": prompt}],
                    **extra,
                )
            except anthropic.APIStatusError as erro:
                transitorio = erro.status_code >= 500
                if transitorio and not ultima:
                    logger.warning(
                        "busca de atividades (Claude): tentativa %d/%d falhou com HTTP %s "
                        "(transitório) — tentando de novo em %.0fs",
                        tentativa, llm.MAX_TENTATIVAS, erro.status_code, llm.BACKOFF_S,
                    )
                    llm._dormir(llm.BACKOFF_S)
                    continue
                raise traduzir_erro_anthropic(erro.status_code, erro.message, self.modelo) from erro
            except anthropic.APITimeoutError as erro:
                if not ultima:
                    llm._dormir(llm.BACKOFF_S)
                    continue
                raise ErroTimeout(
                    f"o modelo {self.modelo} não respondeu em {self.timeout_s:g}s"
                ) from erro
            except anthropic.APIConnectionError as erro:
                if not ultima:
                    llm._dormir(llm.BACKOFF_S)
                    continue
                raise ErroApiIndisponivel(f"falha de rede ao chamar a Anthropic: {erro}") from erro
            except ErroLLM:
                raise
            except Exception as erro:
                raise ErroLLM(f"falha inesperada ao chamar a Anthropic: {erro!r}") from erro
        raise AssertionError("ClienteClaude: loop terminou sem retornar nem levantar")


def criar_cliente_llm() -> ClienteClaude:
    """O LLM da busca: Claude, configurado por ANTHROPIC_* (ver topo). Sem
    ANTHROPIC_API_KEY o servidor sobe igual; a busca que precisar do LLM
    devolve `chave_ausente` e o consultor recebe os candidatos por palavras."""
    return ClienteClaude()
