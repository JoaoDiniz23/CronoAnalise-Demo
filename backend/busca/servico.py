"""
Orquestração da busca de atividades.

    descrição → [nome exato? → resolve sem LLM] → (A) recuperação lexical
              → (B) LLM sobre o CATÁLOGO INTEIRO (lexical vira só pista)
              → validação contra a base oficial → ResultadoBusca

O LLM só é chamado quando a busca determinística não resolve sozinha
(regra do CLAUDE.md). Desde 23/09/2026 ele recebe a base inteira (em
cache no provedor), não só os 10 candidatos lexicais: a busca por
palavras perdia a atividade certa em descrições indiretas ("dinheiro para
abrir um negócio" nunca trazia Capital de Giro), e o LLM não tinha como
achá-la. Pelo mesmo motivo, descrição sem nenhum candidato lexical
("fui almoçar") também vai ao LLM.

Camadas contra atividade inventada:
  1. o catálogo enviado só tem registros da base oficial;
  2. o prompt restringe o LLM aos IDs do catálogo;
  3. a resposta é validada estruturalmente (JSON, tipos, campos);
  4. todo ID é conferido contra o catálogo e contra
     `base.atividade_existe`;
  5. os dados do resultado vêm de `base.atividade_por_id`, não do LLM.
"""

import logging
from typing import Protocol

from backend.dados import Atividade, BaseOficial, carregar_base_oficial

from .interpretador import interpretar_catalogo, montar_sistema_catalogo
from .llm import ClienteLLM, ErroLLM
from .llm_anthropic import criar_cliente_llm
from .modelos import Candidato, DetalheErro, Origem, ResultadoBusca, StatusBusca
from .recuperador import LIMITE_PADRAO, Recuperador, RecuperadorLexical
from .texto import CorretorDigitacao, normalizar, palavras, radicais
from .validador import RespostaInvalida, validar_resposta

log = logging.getLogger(__name__)

# Tamanho máximo aceito para a descrição. Relato de campo é curto; um texto
# enorme só encareceria a chamada ao LLM.
MAX_CARACTERES = 1000


def _posicoes(texto: list[str], trecho: list[str]) -> list[range]:
    n = len(trecho)
    if n == 0:
        return []
    return [range(i, i + n) for i in range(len(texto) - n + 1) if texto[i : i + n] == trecho]


def _cita_os_dois_nomes(ditas: list[str], atividade: Atividade) -> bool:
    """O texto contém o nome da atividade e o do produto em trechos que não
    se sobrepõem. Sem isso, "saque" sozinho resolveria para o registro
    "Saque | Saque", deixando de fora "Saque com Cartão", "Saque no ATM"..."""
    trechos_atividade = _posicoes(ditas, palavras(atividade.atividade))
    trechos_produto = _posicoes(ditas, palavras(atividade.produto))
    return any(
        not set(a) & set(p) for a in trechos_atividade for p in trechos_produto
    )


def correspondencia_exata(texto: str, base: BaseOficial) -> Atividade | None:
    """Resolve sem LLM quando a descrição é, na prática, o próprio nome
    oficial: cita o nome da atividade E o nome do produto de um único
    registro, e não traz nenhuma outra palavra relevante. Qualquer palavra
    a mais (inclusive uma negação) manda a decisão para o LLM."""
    ditas = palavras(texto)
    radicais_ditos = set(radicais(texto))
    achadas = [
        a
        for a in base.listar_atividades()
        if radicais_ditos <= set(radicais(f"{a.atividade} {a.produto}"))
        and _cita_os_dois_nomes(ditas, a)
    ]
    return achadas[0] if len(achadas) == 1 else None


# Até quantas opções um NOME DE ATIVIDADE devolve direto como lista, sem
# LLM. Acima disso ("Dúvida e Suporte (cliente)" existe para 67 produtos)
# a lista não ajuda, e o LLM decide. NOME DE PRODUTO não tem limite
# (decisão do usuário, 23/09/2026): "cartão de crédito" lista as 35
# atividades na hora — não há o que o LLM escolher sem mais pista.
MAX_OPCOES_DIRETAS = 12

# Quantas respostas do LLM ficam em memória (por processo; zera no deploy).
MAX_MEMORIA = 2000

# Decisões do LLM que valem guardar. Falha (quota, timeout, resposta
# recusada) nunca é guardada: a próxima busca tenta de novo.
_STATUS_MEMORIZAVEIS = {
    StatusBusca.ENCONTRADA,
    StatusBusca.AMBIGUA,
    StatusBusca.SEM_CORRESPONDENCIA,
}


def correspondencia_por_nome(texto: str, base: BaseOficial) -> list[Atividade]:
    """Registros cujo nome de atividade OU de produto é exatamente o que foi
    digitado (mesmas palavras relevantes, sem nenhuma a mais — uma negação
    tira a descrição daqui). Ex.: "acompanhamento de metas" → 1 registro;
    "saque" → as atividades do produto Saque."""
    ditos = set(radicais(texto))
    if not ditos:
        return []
    achadas = [
        a
        for a in base.listar_atividades()
        if ditos == set(radicais(a.atividade)) or ditos == set(radicais(a.produto))
    ]
    if len(achadas) == 1 and _e_almoco(achadas[0]):
        return _tempo_nao_produtivo(base) + achadas
    return achadas


# "Almoço" na tabela é só do consultor (código 20), mas o almoço mais comum
# em campo é o do colaborador observado: "Tempo não produtivo" (código 18)
# com "Almoço" no Detalhamento (Guia; decisão do usuário, 28/09/2026).
# Por isso "almoço" digitado sozinho mostra as duas opções, a do
# colaborador primeiro.
MENSAGEM_ALMOCO = (
    "almoço do colaborador: Tempo não produtivo, com \"Almoço\" no "
    "Detalhamento; almoço seu (consultor): Almoço"
)


def _e_almoco(atividade: Atividade) -> bool:
    return set(radicais(atividade.atividade)) == set(radicais("Almoço"))


def _tempo_nao_produtivo(base: BaseOficial) -> list[Atividade]:
    alvo = set(radicais("Tempo não produtivo"))
    return [a for a in base.listar_atividades() if set(radicais(a.atividade)) == alvo]


# Público/segmento dito com todas as letras na descrição → valor como a
# base escreve em `clientes`/`segmento`. O LLM recebe essa informação no
# catálogo mas nem sempre obedece (Haiku ofereceu Capital de Giro, só PJ,
# a um "cliente private"); este filtro garante, sem LLM. Só termos
# inequívocos: "empresa" e "especial" ficam de fora ("abrir uma empresa"
# pode ser PF; "especial" aparece em "cheque especial").
_SEGMENTOS_DITOS = {
    ("alta", "renda"): "Alta Renda",
    ("private",): "Private",
    ("mei",): "MEI",
    ("varejo",): "Varejo",
    ("agro", "pf"): "Agro PF",
    ("agro", "pj"): "Agro PJ",
}
_PUBLICOS_DITOS = {
    ("pf",): "Pessoa Fisica",
    ("pessoa", "fisica"): "Pessoa Fisica",
    ("pj",): "Pessoa Juridica",
    ("pessoa", "juridica"): "Pessoa Juridica",
    ("cnpj",): "Pessoa Juridica",
}


def _dito(ditas: list[str], termos: tuple[str, ...]) -> bool:
    n = len(termos)
    return any(tuple(ditas[i : i + n]) == termos for i in range(len(ditas) - n + 1))


def filtrar_por_publico(texto: str, atividades: list[Atividade]) -> list[Atividade]:
    """Tira as atividades incompatíveis com o segmento/público DITO na
    descrição, pelos próprios campos do registro. Se o filtro esvaziaria a
    lista, devolve a original — nunca some com a resposta."""
    ditas = palavras(texto)
    segmento = next((s for t, s in _SEGMENTOS_DITOS.items() if _dito(ditas, t)), None)
    publico = next((p for t, p in _PUBLICOS_DITOS.items() if _dito(ditas, t)), None)
    if segmento is None and publico is None:
        return atividades

    def compativel(a: Atividade) -> bool:
        if segmento and segmento not in a.segmento_lista:
            return False
        if publico:
            clientes = {normalizar(c) for c in a.clientes_lista}
            if normalizar(publico) not in clientes:
                return False
        return True

    filtradas = [a for a in atividades if compativel(a)]
    return filtradas or atividades


def e_nome_de_produto(texto: str, base: BaseOficial) -> bool:
    """A descrição é exatamente o nome de um produto da base."""
    ditos = set(radicais(texto))
    return bool(ditos) and any(ditos == set(radicais(a.produto)) for a in base.listar_atividades())


def _chave_memoria(texto: str) -> str:
    return " ".join(palavras(texto))


class CotaLLM(Protocol):
    """Quem decide se esta busca ainda pode chamar o LLM (backend/acesso.py:
    cota da pessoa e teto global do dia). `consumir` reserva 1 uso e devolve
    None, ou o motivo do bloqueio ("limite_pessoal"/"limite_diario");
    `devolver` desfaz a reserva quando o LLM falha."""

    def consumir(self) -> str | None: ...
    def devolver(self) -> None: ...


# Texto que vai na resposta da API por tipo de erro. O detalhe cru do
# provedor (status, request_id, corpo do erro) fica só no log do servidor.
MENSAGEM_DE_ERRO = {
    "chave_ausente": "busca inteligente não configurada no servidor",
    "chave_invalida": "busca inteligente com problema de configuração",
    "quota_ou_limite": "busca inteligente sem crédito ou acima do limite do provedor",
    "timeout": "a busca inteligente demorou demais para responder",
    "api_indisponivel": "busca inteligente indisponível no momento",
    "modelo_indisponivel": "busca inteligente sobrecarregada ou indisponível",
    "resposta_invalida": "a busca inteligente devolveu uma resposta fora da base oficial",
}
MENSAGEM_DE_ERRO_PADRAO = "busca inteligente indisponível no momento"


class BuscadorAtividades:
    def __init__(
        self,
        base: BaseOficial,
        recuperador: Recuperador,
        cliente_llm: ClienteLLM | None,
        limite_candidatos: int = LIMITE_PADRAO,
    ):
        self.base = base
        self.recuperador = recuperador
        self.cliente_llm = cliente_llm
        self.limite_candidatos = limite_candidatos
        self._memoria: dict[str, ResultadoBusca] = {}
        self.corretor = CorretorDigitacao(
            t for a in base.listar_atividades() for t in (a.atividade, a.produto, a.subgrupo)
        )
        # Catálogo para o LLM: montado uma vez, texto idêntico em toda
        # chamada (senão o cache do provedor não pega).
        self._sistema = montar_sistema_catalogo(base.listar_atividades())
        self._catalogo = [
            Candidato(atividade=a, pontuacao=0.0, termos_casados=[])
            for a in base.listar_atividades()
        ]

    def buscar(self, texto: str, cota: CotaLLM | None = None) -> ResultadoBusca:
        texto = (texto or "").strip()
        resultado = ResultadoBusca(texto_original=texto, status=StatusBusca.ENTRADA_INSUFICIENTE)

        if not texto:
            resultado.justificativa = "descrição vazia"
            return resultado
        if len(texto) > MAX_CARACTERES:
            resultado.justificativa = (
                f"descrição com mais de {MAX_CARACTERES} caracteres; resuma a observação"
            )
            return resultado
        if not radicais(texto):
            resultado.justificativa = "a descrição não tem palavras que permitam buscar"
            return resultado

        # Erro de digitação corrigido só para a parte sem LLM; o LLM (e a
        # memória) recebem o texto como foi digitado.
        busca = self.corretor.corrigir(texto)
        nota = f' (entendido como "{busca}")' if busca != " ".join(palavras(texto)) else ""

        exata = correspondencia_exata(busca, self.base)
        if exata is not None:
            resultado.status = StatusBusca.ENCONTRADA
            resultado.origem = Origem.BUSCA
            resultado.atividade = exata
            resultado.candidatos = [
                Candidato(atividade=exata, pontuacao=0.0, termos_casados=palavras(busca))
            ]
            resultado.justificativa = "nome da atividade e do produto informados exatamente" + nota
            return resultado

        por_nome = correspondencia_por_nome(busca, self.base)
        if len(por_nome) == 1:
            resultado.status = StatusBusca.ENCONTRADA
            resultado.origem = Origem.BUSCA
            resultado.atividade = por_nome[0]
            resultado.justificativa = "nome oficial informado exatamente" + nota
            return resultado
        if len(por_nome) >= 2 and (
            len(por_nome) <= MAX_OPCOES_DIRETAS or e_nome_de_produto(busca, self.base)
        ):
            resultado.status = StatusBusca.AMBIGUA
            resultado.origem = Origem.BUSCA
            resultado.alternativas = por_nome
            resultado.justificativa = (
                MENSAGEM_ALMOCO
                if any(_e_almoco(a) for a in por_nome) and len(por_nome) == 2
                else "há mais de uma atividade com esse nome; escolha a que foi feita"
            ) + nota
            return resultado

        chave = _chave_memoria(texto)
        lembrado = self._memoria.get(chave)
        if lembrado is not None:
            # Resposta da memória não chama o LLM: não gasta cota.
            return lembrado.model_copy(update={"texto_original": texto, "consumiu_llm": False})

        candidatos = self.recuperador.buscar(busca, self.limite_candidatos)
        resultado.candidatos = candidatos
        resultado = self._interpretar(resultado, candidatos, cota)
        if resultado.origem == Origem.LLM and resultado.status in _STATUS_MEMORIZAVEIS:
            if len(self._memoria) >= MAX_MEMORIA:
                self._memoria.pop(next(iter(self._memoria)))  # sai a mais antiga
            self._memoria[chave] = resultado
        return resultado

    def _interpretar(
        self, resultado: ResultadoBusca, candidatos: list[Candidato], cota: CotaLLM | None = None
    ) -> ResultadoBusca:
        if self.cliente_llm is None:
            resultado.status = StatusBusca.LLM_INDISPONIVEL
            resultado.erro = DetalheErro(tipo="llm_desativado", mensagem="nenhum LLM configurado")
            return resultado
        bloqueio = cota.consumir() if cota is not None else None
        if bloqueio:
            # Cota da pessoa ou teto global do dia acabou: segue sem LLM,
            # com os candidatos por palavras.
            resultado.status = StatusBusca.LLM_INDISPONIVEL
            resultado.erro = DetalheErro(
                tipo=bloqueio, mensagem="limite diário de buscas inteligentes atingido"
            )
            return resultado
        resultado.consumiu_llm = cota is not None

        resultado.modelo = self.cliente_llm.modelo
        try:
            bruta = interpretar_catalogo(
                self.cliente_llm, self._sistema, resultado.texto_original, candidatos
            )
        except ErroLLM as erro:
            if cota is not None:
                cota.devolver()  # falha do provedor não gasta a cota da pessoa
                resultado.consumiu_llm = False
            log.warning("LLM indisponível (%s): %s", erro.tipo, erro)
            resultado.status = StatusBusca.LLM_INDISPONIVEL
            resultado.erro = DetalheErro(
                tipo=erro.tipo,
                mensagem=MENSAGEM_DE_ERRO.get(erro.tipo, MENSAGEM_DE_ERRO_PADRAO),
            )
            return resultado

        try:
            decisao = validar_resposta(bruta, self._catalogo, self.base)
        except RespostaInvalida as erro:
            log.warning(
                "resposta do LLM recusada: %s | modelo=%s | candidatos=%s | resposta=%.500r",
                erro.motivo,
                resultado.modelo,
                [c.atividade.id for c in candidatos],  # pistas lexicais
                erro.resposta_bruta,
            )
            resultado.status = StatusBusca.RESPOSTA_INVALIDA
            resultado.erro = DetalheErro(
                tipo="resposta_invalida", mensagem=MENSAGEM_DE_ERRO["resposta_invalida"]
            )
            return resultado

        # Uma linha por decisão: é o que permite achar, no log do piloto, a
        # próxima descrição que o modelo confunde (29/09/2026).
        log.info(
            "decisão do LLM: texto=%r decisao=%s ids=%s acao=%r ajustada=%s modelo=%s",
            resultado.texto_original,
            decisao.decisao,
            [decisao.atividade.id] if decisao.atividade else [a.id for a in decisao.alternativas],
            decisao.acao_observada,
            decisao.ajustada_pela_comparacao,
            resultado.modelo,
        )
        resultado.origem = Origem.LLM
        resultado.justificativa = decisao.justificativa
        if decisao.decisao == "encontrada":
            resultado.status = StatusBusca.ENCONTRADA
            resultado.atividade = decisao.atividade
            resultado.tnp_do_consultor = decisao.tnp_do_consultor
        elif decisao.decisao == "ambigua":
            resultado.status = StatusBusca.AMBIGUA
            resultado.alternativas = decisao.alternativas
            compativeis = filtrar_por_publico(resultado.texto_original, decisao.alternativas)
            if len(compativeis) < len(decisao.alternativas):
                # A justificativa do LLM citava as opções removidas.
                resultado.justificativa = (
                    "opções compatíveis com o público/segmento informado na descrição"
                )
                resultado.alternativas = compativeis
                if len(compativeis) == 1:
                    resultado.status = StatusBusca.ENCONTRADA
                    resultado.atividade = compativeis[0]
                    resultado.alternativas = []
        else:
            resultado.status = StatusBusca.SEM_CORRESPONDENCIA
        return resultado


def criar_buscador(
    base: BaseOficial | None = None, cliente_llm: ClienteLLM | None = None
) -> BuscadorAtividades:
    """Buscador padrão: base oficial + recuperador lexical + LLM escolhido
    pelo ambiente (`criar_cliente_llm`: Claude)."""
    base = base or carregar_base_oficial()
    return BuscadorAtividades(
        base=base,
        recuperador=RecuperadorLexical(base),
        cliente_llm=cliente_llm or criar_cliente_llm(),
    )
