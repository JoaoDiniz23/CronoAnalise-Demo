"""
Autenticação mínima + guardrails de custo (BLOCO 3 do plano de fechamento
do MVP, CLAUDE.md, 20/09/2026).

Por que isto existe: uma rota aberta gastaria o crédito do LLM de graça
para qualquer um. Este módulo cobre isso com o mínimo necessário — sem banco, sem usuários, sem OAuth,
consistente com o resto do projeto (CLAUDE.md, "Arquitetura":
"Não introduzir banco/fila/autenticação complexa por antecipação").

1. AUTENTICAÇÃO — uma senha compartilhada (`ACESSO_SENHA`), um cookie de
   sessão assinado (`itsdangerous`, nunca um token que o cliente possa
   forjar) guardando o nome do consultor — escolhido na lista
   `ACESSO_CONSULTORES` ou, sem a lista, digitado no login. Não há
   verificação de identidade real — é o mesmo nível de proteção que uma
   senha de Wi-Fi de escritório: impede acesso casual/automatizado, não
   impede um consultor mal-intencionado. Suficiente para o MVP, registrado
   como limitação conhecida.

2. GUARDRAIL DE CUSTO — só as buscas que chegam de fato ao LLM contam:
   cota por pessoa por dia de Brasília (`usos_llm_por_pessoa_dia`, padrão
   60) e teto global diário (`chamadas_globais_por_dia`, padrão 1500).
   Busca sem LLM (nome exato, palavras, memória) é ilimitada — não custa
   nada e nunca pode esgotar o teto dos outros (25/09/2026). Esgotada
   qualquer das duas, a busca segue sem LLM — nunca bloqueia o consultor. (Os limites de análise de PDF da folha saíram junto
   com a rota, removida em 22/09/2026.)
   Contadores em memória (reiniciam se o processo reiniciar — é o mesmo
   modelo de "sem persistência" já adotado no resto do projeto, ver
   `.env`/histórico/cronômetro). Quando um limite estoura, a resposta diz
   o motivo (`erro.tipo`), nunca em silêncio.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

NOME_DO_COOKIE = "cronoanalise_sessao"
SALT_DO_COOKIE = "cronoanalise-acesso-v1"
VALIDADE_COOKIE_S = 30 * 24 * 60 * 60  # 30 dias — sessão de campo, não web comum


# ==========================================================================
# Senha e cookie de sessão
# ==========================================================================


class ErroAcessoNaoConfigurado(Exception):
    """`ACESSO_SENHA` não está definida — falha ruidosa, nunca abre a
    aplicação sem senha por omissão de configuração."""


def _senha_configurada() -> str:
    senha = os.environ.get("ACESSO_SENHA", "").strip()
    if not senha:
        raise ErroAcessoNaoConfigurado(
            "ACESSO_SENHA não configurada no ambiente/.env — defina antes de "
            "expor o sistema fora de localhost."
        )
    return senha


def senha_confere(tentativa: str) -> bool:
    """Comparação em tempo constante — evita vazar, por timing, quantos
    caracteres da senha a tentativa acertou."""
    try:
        esperada = _senha_configurada()
    except ErroAcessoNaoConfigurado:
        return False
    return hmac.compare_digest(tentativa.strip(), esperada)


def consultores_permitidos() -> list[str]:
    """Nomes da equipe (`ACESSO_CONSULTORES`, separados por ";" ou quebra
    de linha), em ordem alfabética sem acento. Vazio = login com nome livre
    (como antes). Fica no ambiente, não no repositório: nome de pessoa não
    precisa ir para o Git. Com a lista, o nome vira chave estável da cota
    diária de LLM e do log de auditoria ("Ana" e "ana souza" não são mais
    duas pessoas)."""
    bruto = os.environ.get("ACESSO_CONSULTORES", "")
    nomes = {" ".join(n.split()) for n in bruto.replace("\n", ";").split(";") if n.strip()}
    return sorted(nomes, key=_chave_ordem)


def _chave_ordem(nome: str) -> str:
    decomposto = unicodedata.normalize("NFD", nome.casefold())
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def _chave_de_assinatura() -> str:
    """`ACESSO_SECRET_KEY`, se definida; senão deriva de `ACESSO_SENHA` (com
    salt fixo, para não ser literalmente a senha em texto claro dentro do
    cookie assinado). Documentar: para produção de verdade, defina
    `ACESSO_SECRET_KEY` separada — evita que vazar o segredo do cookie
    exponha também a senha de login."""
    secreta = os.environ.get("ACESSO_SECRET_KEY", "").strip()
    if secreta:
        return secreta
    return hashlib.sha256(
        (_senha_configurada() + "|" + SALT_DO_COOKIE).encode("utf-8")
    ).hexdigest()


def _serializador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_chave_de_assinatura(), salt=SALT_DO_COOKIE)


@dataclass(frozen=True)
class Sessao:
    """O que o cookie assinado carrega. `sessao_id` é gerado uma vez por
    login (`criar_cookie`); é a chave da cota de LLM quando o login não
    tem nome (ver `buscar_atividade` em `main.py`)."""

    nome: str
    sessao_id: str


def criar_cookie(nome_consultor: str) -> str:
    """Assina `{"nome": ..., "sessao_id": ...}`. `sessao_id` é um UUID
    novo a cada chamada (a cada login) — nada mais vai no cookie (nenhum
    dado da folha, nenhuma credencial reaproveitável fora deste sistema)."""
    nome = nome_consultor.strip() or "consultor"
    return _serializador().dumps({"nome": nome, "sessao_id": uuid.uuid4().hex})


def validar_cookie(valor: str | None) -> Sessao | None:
    """Devolve a `Sessao` (nome + sessao_id) se o cookie é válido e não
    expirou; `None` em qualquer outro caso (ausente, adulterado, expirado,
    senha trocada). Nunca levanta — quem chama trata `None` como "sem
    sessão"."""
    if not valor:
        return None
    try:
        dados = _serializador().loads(valor, max_age=VALIDADE_COOKIE_S)
    except (BadSignature, SignatureExpired):
        return None
    except Exception:
        # Qualquer outra falha de parsing (cookie truncado, não-UTF8 etc.)
        # também é "sem sessão válida" — nunca deixa uma exceção subir e
        # virar 500 por causa de um cookie malformado.
        return None
    if not isinstance(dados, dict):
        return None
    nome = dados.get("nome")
    sessao_id = dados.get("sessao_id")
    if not (isinstance(nome, str) and nome and isinstance(sessao_id, str) and sessao_id):
        return None
    return Sessao(nome=nome, sessao_id=sessao_id)


# ==========================================================================
# Guardrails de custo — contadores em memória, por dia
# ==========================================================================


@dataclass(frozen=True)
class LimitesDeUso:
    """Nenhum destes números é medido — são tetos operacionais de partida,
    para nunca deixar a rota sem limite nenhum. Ajustar por variável de
    ambiente conforme o uso real em campo mostrar o número certo."""

    chamadas_globais_por_dia: int = 1500
    # Buscas que chegam de fato ao LLM, por pessoa (nome do login), por dia
    # de Brasília. Decisão do usuário (23/09/2026): teto de custo — busca
    # sem LLM (nome exato, offline, memória) continua ilimitada.
    usos_llm_por_pessoa_dia: int = 60


def _limites_do_ambiente() -> LimitesDeUso:
    def _ler(nome_env: str, padrao: int) -> int:
        # BUG CORRIGIDO (achado no smoke test do ajuste de guardrails):
        # `numero if numero > 0 else padrao` tratava 0 como "não
        # configurado" e caía no padrão em silêncio -- um operador
        # configurando ACESSO_LIMITE_GLOBAL_DIA=0 para bloquear tudo
        # (ex.: emergência de orçamento) via `>= 0` tinha o valor
        # IGNORADO e o guardrail deixava passar, inclusive chamando o
        # modelo de verdade. 0 é um valor explícito e válido (bloqueia
        # tudo); só um valor NEGATIVO cai no padrão, por ser inválido.
        valor = os.environ.get(nome_env, "").strip()
        if not valor:
            return padrao
        try:
            numero = int(valor)
        except ValueError:
            return padrao
        return numero if numero >= 0 else padrao

    return LimitesDeUso(
        chamadas_globais_por_dia=_ler(
            "ACESSO_LIMITE_GLOBAL_DIA", LimitesDeUso.chamadas_globais_por_dia
        ),
        usos_llm_por_pessoa_dia=_ler(
            "ACESSO_LIMITE_LLM_PESSOA_DIA", LimitesDeUso.usos_llm_por_pessoa_dia
        ),
    )


# Dia de Brasília (UTC-3 fixo: o Brasil não tem horário de verão desde
# 2019). O consultor trabalha em horário local — o contador não pode virar
# às 21h.
FUSO_BRASILIA = timezone(timedelta(hours=-3))


class ContadorDeUso:
    """Contadores em memória, isolados numa instância — os testes criam a
    sua própria (nunca compartilham contagem com o processo real), e o
    servidor usa uma instância única (`contador_padrao`, abaixo).

    Chave por data: o teto de chat é "por dia" e reinicia sozinho na
    virada da data, sem faxina.
    """

    def __init__(self, limites: LimitesDeUso | None = None):
        self._limites = limites or _limites_do_ambiente()
        self._lock = threading.Lock()
        self._chamadas_globais: dict[str, int] = {}
        self._usos_llm: dict[tuple[str, str], int] = {}

    @property
    def limite_llm_por_pessoa(self) -> int:
        return self._limites.usos_llm_por_pessoa_dia

    def _hoje(self) -> str:
        return datetime.now(FUSO_BRASILIA).date().isoformat()

    @staticmethod
    def _chave_pessoa(pessoa: str) -> str:
        return " ".join((pessoa or "").lower().split())

    def consumir_uso_llm(self, pessoa: str) -> str | None:
        """Reserva 1 uso do LLM para a pessoa hoje, no teto global e na cota
        da pessoa. None = liberado; senão o motivo do bloqueio
        ("limite_diario" ou "limite_pessoal") e a busca segue sem LLM.
        Busca que não chega ao LLM não passa por aqui: é ilimitada."""
        hoje, chave = self._hoje(), self._chave_pessoa(pessoa)
        with self._lock:
            # Faxina: só o dia corrente importa.
            for antiga in [k for k in self._usos_llm if k[0] != hoje]:
                del self._usos_llm[antiga]
            for antigo in [d for d in self._chamadas_globais if d != hoje]:
                del self._chamadas_globais[antigo]
            globais = self._chamadas_globais.get(hoje, 0)
            if globais >= self._limites.chamadas_globais_por_dia:
                return "limite_diario"
            usados = self._usos_llm.get((hoje, chave), 0)
            if usados >= self._limites.usos_llm_por_pessoa_dia:
                return "limite_pessoal"
            self._usos_llm[(hoje, chave)] = usados + 1
            self._chamadas_globais[hoje] = globais + 1
            return None

    def devolver_uso_llm(self, pessoa: str) -> None:
        """O LLM falhou (quota, rede...): o uso reservado não conta."""
        hoje, chave = self._hoje(), self._chave_pessoa(pessoa)
        with self._lock:
            if self._usos_llm.get((hoje, chave), 0) > 0:
                self._usos_llm[(hoje, chave)] -= 1
            if self._chamadas_globais.get(hoje, 0) > 0:
                self._chamadas_globais[hoje] -= 1

    def usos_llm_restantes(self, pessoa: str) -> int:
        hoje, chave = self._hoje(), self._chave_pessoa(pessoa)
        with self._lock:
            usados = self._usos_llm.get((hoje, chave), 0)
        return max(0, self._limites.usos_llm_por_pessoa_dia - usados)


# Instância única do processo — mesma decisão de `@lru_cache` do resto de
# `backend/main.py`: um estado, criado uma vez, vivo enquanto o servidor
# estiver de pé.
contador_padrao = ContadorDeUso()
