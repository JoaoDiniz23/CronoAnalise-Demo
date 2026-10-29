"""
Testes do cliente Claude (`backend/busca/llm_anthropic.py`).

NENHUM TESTE AQUI CHAMA A ANTHROPIC DE VERDADE — SDK falso roteirizado.
"""

import anthropic
import httpx
import pytest

from backend.busca import llm as modulo_llm
from backend.busca.llm import (
    ErroApiIndisponivel,
    ErroChaveInvalida,
    ErroModeloIndisponivel,
    ErroQuota,
    ErroTimeout,
)
from backend.busca.llm_anthropic import (
    ClienteClaude,
    criar_cliente_llm,
)

_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture(autouse=True)
def sem_backoff_de_verdade(monkeypatch):
    monkeypatch.setattr(modulo_llm, "_dormir", lambda segundos: None)


def erro_http(codigo, mensagem="erro"):
    resposta = httpx.Response(codigo, request=_REQ)
    return anthropic.APIStatusError(mensagem, response=resposta, body=None)


def resposta_ok(texto='{"decisao": "nenhuma"}'):
    bloco = type("Bloco", (), {"type": "text", "text": texto})()
    uso = type("Uso", (), {"input_tokens": 1000, "output_tokens": 80})()
    return type("Resposta", (), {"content": [bloco], "usage": uso})()


class _SdkFalso:
    def __init__(self, *efeitos):
        self._efeitos = list(efeitos)
        self.chamadas = 0
        self.ultimos_args = None
        self.messages = self

    def create(self, **kwargs):
        self.chamadas += 1
        self.ultimos_args = kwargs
        efeito = self._efeitos.pop(0)
        if isinstance(efeito, Exception):
            raise efeito
        return efeito


def _claude_com(*efeitos):
    cliente = ClienteClaude(chave_api="chave-de-teste", modelo="claude-x", timeout_s=5)
    sdk = _SdkFalso(*efeitos)
    cliente._cliente = sdk
    return cliente, sdk


def test_sucesso_devolve_texto_e_registra_consumo():
    cliente, sdk = _claude_com(resposta_ok('{"a": 1}'))
    assert cliente.gerar("prompt", None) == '{"a": 1}'
    assert sdk.ultimos_args["model"] == "claude-x"
    assert "temperature" not in sdk.ultimos_args  # SDK atual não aceita mais
    assert cliente.ultimo_consumo.tokens_entrada == 1000
    assert cliente.ultimo_consumo.tokens_saida == 80


@pytest.mark.parametrize("codigo", [500, 503, 529])
def test_erro_transitorio_tem_uma_nova_tentativa(codigo):
    cliente, sdk = _claude_com(erro_http(codigo), resposta_ok())
    cliente.gerar("prompt", None)
    assert sdk.chamadas == 2


def test_transitorio_nas_duas_tentativas_vira_erro_tipado():
    cliente, sdk = _claude_com(erro_http(529), erro_http(529))
    with pytest.raises(ErroModeloIndisponivel):
        cliente.gerar("prompt", None)
    assert sdk.chamadas == 2


@pytest.mark.parametrize(
    "codigo, mensagem, classe",
    [
        (429, "rate limit", ErroQuota),
        (401, "invalid x-api-key", ErroChaveInvalida),
        (403, "forbidden", ErroChaveInvalida),
        (404, "model not found", ErroModeloIndisponivel),
        (400, "Your credit balance is too low", ErroQuota),
    ],
)
def test_erro_nao_transitorio_sobe_na_primeira_tentativa(codigo, mensagem, classe):
    cliente, sdk = _claude_com(erro_http(codigo, mensagem))
    with pytest.raises(classe):
        cliente.gerar("prompt", None)
    assert sdk.chamadas == 1


def test_timeout_e_rede_tem_retry_e_depois_erro_tipado():
    cliente, sdk = _claude_com(
        anthropic.APITimeoutError(request=_REQ), anthropic.APITimeoutError(request=_REQ)
    )
    with pytest.raises(ErroTimeout):
        cliente.gerar("prompt", None)
    assert sdk.chamadas == 2

    cliente, sdk = _claude_com(
        anthropic.APIConnectionError(request=_REQ), anthropic.APIConnectionError(request=_REQ)
    )
    with pytest.raises(ErroApiIndisponivel):
        cliente.gerar("prompt", None)
    assert sdk.chamadas == 2


# ==========================================================================
# Reserva entre provedores
# ==========================================================================


# ==========================================================================
# Criação do cliente pelo ambiente
# ==========================================================================


def test_criar_cliente_llm_e_sempre_claude(monkeypatch):
    monkeypatch.setattr("backend.busca.llm_anthropic.load_dotenv", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Sem chave o servidor sobe igual; a falta só aparece na chamada.
    assert isinstance(criar_cliente_llm(), ClienteClaude)
