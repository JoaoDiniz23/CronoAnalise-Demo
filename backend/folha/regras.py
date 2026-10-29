"""
As regras de validação da folha, uma função por regra.

FONTE DO CATÁLOGO: `docs/historico/prd_validador_folhas.md`, seção 7.5,
que cita a fonte documental (Manual de Coleta / Guia de atualização) de
cada regra. Nenhuma regra foi inventada aqui e nenhuma interpretação foi
alterada. O catálogo tem **26** entradas (o plano histórico as chamava
de "25 regras" — a contagem estava errada, não o catálogo).

FORMATO: toda regra é uma função `(folha, base) -> list[PontoParaRevisar]`.
Nenhuma regra chama outra nem sabe que outra existe. Isso é o que faz um
apontamento errado ficar contido numa regra só.

DOMÍNIOS: Classificação, Local, Forma de Atendimento, Clientes e as
siglas de Segmento vêm SEMPRE de `BaseOficial`. Nenhuma lista de domínio
é copiada para este módulo. As duas listas literais que existem aqui
(os quatro termos genéricos proibidos e o par de códigos TNP) não são
domínios: são proibições/gatilhos citados nominalmente pelo Guia.

QUATRO REGRAS DO CATÁLOGO NÃO ESTÃO IMPLEMENTADAS — ver `REGRAS_PENDENTES`
no fim do arquivo, com o motivo de cada uma. Elas não foram completadas
por inferência.
"""

import re
import unicodedata

from backend.dados import BaseOficial

from .modelos import Celula, Conjunto, EstadoLeitura, Folha
from .resultado import PontoParaRevisar, TipoPonto

# Nome legível de cada coluna, para as mensagens ao consultor.
NOME_DO_CAMPO = {
    "data": "Data", "uniorg": "Uniorg", "loja": "Loja", "nome": "Nome",
    "matricula": "Matrícula", "cargo": "Cargo",
    "id_responsavel": "ID Responsável pela coleta",
    "numero_folha": "Número da Folha de coleta",
    "num_processo": "# Processos", "detalhamento": "Detalhamento de Atividade",
    "produto": "Produto/Ação Descritiva", "segmento": "Segmento",
    "agenda_certo": "Agenda CERTO?", "classificacao": "Classificação",
    "local": "Local da Atividade", "atendimento": "Forma de Atendimento",
    "clientes": "Clientes", "venda_concluida": "Venda/Processo foi concluído?",
    "hora": "Hora", "minutos": "Minutos", "segundos": "Segundos",
    "quantidade": "Quantidade de vezes", "ocorrencia": "Ocorrência",
}


# ==========================================================================
# DECISAO DE PRODUTO (20/09/2026) -- coluna "Ocorrencia" fora do escopo
#
# Ocorrencia esta FORA do escopo funcional do software: nao deve gerar
# feedback ao consultor, nao deve aparecer como ponto de revisao e nao
# deve ser tratada como regra de negocio no relatorio final.
#
# O que NAO foi feito, e por que:
#
#   - A coluna NAO foi removida de `Linha.CAMPOS`. Ela existe fisicamente
#     na folha (o molde oficial imprime "Ocorrencia (Sim ou Nao)"), e
#     `linha_sem_brancos` cobra todas as colunas de uma linha em uso. Se a
#     leitura deixasse de preencher esta celula, ela chegaria como VAZIA e
#     a regra acusaria um branco INEXISTENTE em cada linha preenchida de
#     cada ficha -- dezenas de apontamentos falsos por PDF.
#
#   - Nenhuma regra foi desligada. Todo ponto gerado a partir desta coluna
#     (por `sn_ocorrencia` ou por `linha_sem_brancos`) carrega
#     `campo == "ocorrencia"`, entao UM filtro no limite do relatorio
#     cobre os dois casos. Desligar regra aqui mudaria um contrato ja
#     testado sem necessidade.
#
# Onde o isolamento acontece: em `backend/analise/`, ao montar o relatorio
# do PDF -- essa camada ainda nao existe (e do Passo 2). Ate la, o motor
# segue com o comportamento de sempre, e esta constante e o contrato que
# a camada de analise vai consumir.
# ==========================================================================

CAMPOS_FORA_DO_ESCOPO = ("ocorrencia",)


def fora_do_escopo_funcional(ponto: PontoParaRevisar) -> bool:
    """O ponto e sobre um campo que o produto nao comenta com o consultor."""
    return ponto.campo in CAMPOS_FORA_DO_ESCOPO


def _rotulo(campo: str) -> str:
    return NOME_DO_CAMPO.get(campo, campo)


def _normalizar(texto: str) -> str:
    """Minúsculas e sem acento. A folha é preenchida em letra bastão
    (Manual, p. 41), então caixa e acento não são o dado — comparar de
    forma sensível a eles reprovaria folha certa."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.strip().lower()


def _inteiro(celula: Celula) -> int | None:
    """Valor da célula como inteiro, ou None se não for um inteiro.
    Não converte "4 " -> 4 por engano: usa o texto já sem espaços."""
    texto = celula.texto
    if not re.fullmatch(r"\d+", texto):
        return None
    return int(texto)


def _ponto(regra, mensagem, *, tipo=TipoPonto.ERRO, linha=None, campo=None):
    return PontoParaRevisar(
        regra=regra, tipo=tipo, mensagem=mensagem, linha=linha, campo=campo
    )


# ==========================================================================
# Tratamento de incerteza de leitura
#
# NÃO é regra do catálogo: é o mecanismo do PRD, seções 6 e 8
# ("Confirmação necessária"). Precisa vir antes de tudo, porque célula
# ilegível não pode cair em nenhuma outra regra — nem como valor
# assumido, nem como campo em branco.
# ==========================================================================

def leitura_incerta(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    pontos = []
    for campo, celula in folha.cabecalho.celulas():
        if celula.estado is EstadoLeitura.ILEGIVEL:
            pontos.append(_ponto(
                "leitura_incerta",
                f"Não consegui ler o campo {_rotulo(campo)} do cabeçalho. "
                "Confira o que está escrito.",
                tipo=TipoPonto.CONFIRMAR, campo=campo,
            ))
    for linha in folha.linhas:
        for campo, celula in linha.celulas():
            if celula.estado is EstadoLeitura.ILEGIVEL:
                pontos.append(_ponto(
                    "leitura_incerta",
                    f"Não consegui ler {_rotulo(campo)} na linha {linha.numero}. "
                    "Confira o que está escrito.",
                    tipo=TipoPonto.CONFIRMAR, linha=linha.numero, campo=campo,
                ))
    return pontos


# ==========================================================================
# CABEÇALHO
# ==========================================================================

def cab_completo(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Manual, p. 44: "Todas as partes do cabeçalho precisam ser
    preenchidas (MATRÍCULA E CARGO NÃO podem ser esquecidas)."."""
    return [
        _ponto("cab_completo",
               f"O campo {_rotulo(campo)} do cabeçalho está em branco.",
               campo=campo)
        for campo, celula in folha.cabecalho.celulas()
        if celula.estado is EstadoLeitura.VAZIA
    ]


def cab_nome(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Manual, p. 44: "NOME + SOBRENOME (do mapeado)"."""
    celula = folha.cabecalho.nome
    if not celula.tem_valor or len(celula.texto.split()) >= 2:
        return []
    return [_ponto("cab_nome",
                   "O campo Nome deve trazer nome e sobrenome do colaborador "
                   "mapeado.", campo="nome")]


# Lojas da cronoanálise (lista FICTÍCIA nesta demo). O campo
# Loja leva o NOME da loja, não o tipo (Universal, Digital, Empresas...).
LOJAS = (
    "LARGO DO MERCADO", "JARDIM DAS FLORES", "AVENIDA PRINCIPAL",
    "SHOPPING NORTE", "PRACA CENTRAL", "VILA NOVA",
)


def _sem_pontuacao(texto: str) -> str:
    return " ".join(re.sub(r"[^\w ]", " ", _normalizar(texto)).split())


_LOJAS_NORMALIZADAS = {_sem_pontuacao(loja) for loja in LOJAS}


def cab_loja(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Loja fora da lista de lojas. ALERTA, não ERRO: letra manuscrita e
    abreviação ("MAL." por "MARECHAL") podem fugir da grafia da lista."""
    celula = folha.cabecalho.loja
    if not celula.tem_valor or _sem_pontuacao(celula.texto) in _LOJAS_NORMALIZADAS:
        return []
    return [_ponto("cab_loja",
                   f"A loja \"{celula.texto}\" não está na lista de lojas. "
                   "Confira o nome (não o tipo da loja).",
                   tipo=TipoPonto.ALERTA, campo="loja")]


def cab_data_formato(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Manual, p. 44: "Data SEMPRE no formato dia/mês (sem colocar o ano)"."""
    celula = folha.cabecalho.data
    if not celula.tem_valor:
        return []

    casou = re.fullmatch(r"(\d{1,2})/(\d{1,2})", celula.texto)
    if casou:
        dia, mes = int(casou.group(1)), int(casou.group(2))
        if 1 <= dia <= 31 and 1 <= mes <= 12:
            return []
    return [_ponto("cab_data_formato",
                   "A Data deve estar no formato dia/mês, sem o ano "
                   "(por exemplo: 13/08).", campo="data")]


# ==========================================================================
# LINHA A LINHA
# ==========================================================================

def linha_sem_brancos(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Manual, p. 43: "Não deixe valores em branco. Sempre preencha
    todos os campos." Só vale para linha usada — folha de 15 linhas
    quase nunca é preenchida inteira."""
    return [
        _ponto("linha_sem_brancos",
               f"A linha {linha.numero} está com {_rotulo(campo)} em branco.",
               linha=linha.numero, campo=campo)
        for linha in folha.linhas_em_uso
        for campo, celula in linha.celulas()
        if celula.estado is EstadoLeitura.VAZIA
    ]


def linha_sequencial(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Preenchimento a partir da linha 1, sem pular linhas.

    Fonte: decisão do projeto (PRD, seção 7.5) — é a única regra do
    catálogo que não vem de documento do cliente.
    """
    usadas = sorted(linha.numero for linha in folha.linhas_em_uso)
    if not usadas:
        return []

    esperadas = list(range(1, len(usadas) + 1))
    if usadas == esperadas:
        return []

    puladas = sorted(set(esperadas) - set(usadas))
    return [_ponto("linha_sequencial",
                   "O preenchimento deve começar na linha 1 e seguir sem pular "
                   f"linhas. Sem preenchimento: {', '.join(map(str, puladas))}.")]


def _regra_s_ou_n(nome_regra: str, campo: str):
    def regra(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
        pontos = []
        for linha in folha.linhas_em_uso:
            celula = getattr(linha, campo)
            if celula.tem_valor and celula.texto.upper() not in ("S", "N"):
                pontos.append(_ponto(
                    nome_regra,
                    f"Na linha {linha.numero}, {_rotulo(campo)} aceita apenas "
                    f"S ou N. Está escrito \"{celula.texto}\".",
                    linha=linha.numero, campo=campo,
                ))
        return pontos

    regra.__name__ = nome_regra
    regra.__doc__ = f"Manual, p. 42-43: {_rotulo(campo)} é S ou N."
    return regra


sn_agenda = _regra_s_ou_n("sn_agenda", "agenda_certo")
sn_venda = _regra_s_ou_n("sn_venda", "venda_concluida")
sn_ocorrencia = _regra_s_ou_n("sn_ocorrencia", "ocorrencia")


def _regra_dominio(nome_regra: str, campo: str, codigos_de):
    """Monta uma regra de coluna de domínio fechado.

    `codigos_de` recebe a BaseOficial e devolve os códigos aceitos — o
    domínio nunca é escrito aqui.
    """

    def regra(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
        aceitos = sorted(codigos_de(base))
        legiveis = ", ".join(map(str, aceitos))
        pontos = []
        for linha in folha.linhas_em_uso:
            celula = getattr(linha, campo)
            if not celula.tem_valor:
                continue
            if _inteiro(celula) not in aceitos:
                pontos.append(_ponto(
                    nome_regra,
                    f"Na linha {linha.numero}, {_rotulo(campo)} está com "
                    f"\"{celula.texto}\". Os valores aceitos são: {legiveis}.",
                    linha=linha.numero, campo=campo,
                ))
        return pontos

    regra.__name__ = nome_regra
    return regra


class_dominio = _regra_dominio(
    "class_dominio", "classificacao", lambda base: base.codigos_classificacao()
)
local_dominio = _regra_dominio(
    "local_dominio", "local", lambda base: base.local_da_atividade.keys()
)
aten_dominio = _regra_dominio(
    "aten_dominio", "atendimento", lambda base: base.forma_de_atendimento.keys()
)
clientes_dominio = _regra_dominio(
    "clientes_dominio", "clientes", lambda base: base.clientes_legenda.keys()
)


def _regra_faixa(nome_regra: str, campo: str, minimo: int, maximo: int | None):
    def regra(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
        pontos = []
        for linha in folha.linhas_em_uso:
            celula = getattr(linha, campo)
            if not celula.tem_valor:
                continue
            valor = _inteiro(celula)
            if valor is None or valor < minimo or (maximo is not None and valor > maximo):
                limite = (f"entre {minimo} e {maximo}" if maximo is not None
                          else f"a partir de {minimo}")
                pontos.append(_ponto(
                    nome_regra,
                    f"Na linha {linha.numero}, {_rotulo(campo)} está com "
                    f"\"{celula.texto}\". O valor deve ser um número {limite}.",
                    linha=linha.numero, campo=campo,
                ))
        return pontos

    regra.__name__ = nome_regra
    return regra


tempo_minutos = _regra_faixa("tempo_minutos", "minutos", 0, 59)
tempo_segundos = _regra_faixa("tempo_segundos", "segundos", 0, 59)
quantidade_min = _regra_faixa("quantidade_min", "quantidade", 1, None)


# ==========================================================================
# COERÊNCIA DENTRO DA LINHA
# ==========================================================================

# Códigos de Forma de Atendimento que são atendimento remoto. Não é um
# domínio (o domínio vem da base): é o recorte citado pelo Guia, seção
# 2.1 — "ligação, e-mail, WhatsApp, chat".
ATENDIMENTO_REMOTO = (1, 2, 4, 6)
LOCAL_PLATAFORMA = 4

# Guia, seção 1.4: 18 é o tempo parado do mapeado, 20 o do consultor.
CLASSIFICACOES_TNP_COM_PRODUTO_FIXO = (18, 20)


def coer_segmento_m(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Guia, seção 1.1: MEI (sigla MEI) é sempre Cliente PJ."""
    sigla_m = next(
        (s for s in (base.segmento_legenda or {}) if _normalizar(s) == "mei"), None
    )
    if sigla_m is None:
        return []

    pontos = []
    for linha in folha.linhas_em_uso:
        if not linha.segmento.tem_valor or not linha.clientes.tem_valor:
            continue
        if _normalizar(linha.segmento.texto) != _normalizar(sigla_m):
            continue
        if _inteiro(linha.clientes) != 2:
            pontos.append(_ponto(
                "coer_segmento_m",
                f"Na linha {linha.numero}, o Segmento é {sigla_m} "
                "(MEI), então Clientes deve ser 2 (Cliente PJ).",
                linha=linha.numero, campo="clientes",
            ))
    return pontos


def coer_remoto_plat(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Guia, seção 2.1: "Se o atendimento foi remoto (ligação, e-mail,
    WhatsApp, chat), o local é 4 - Plataforma, porque é de lá que o
    especialista atendeu."."""
    pontos = []
    for linha in folha.linhas_em_uso:
        if not linha.atendimento.tem_valor or not linha.local.tem_valor:
            continue
        if _inteiro(linha.atendimento) not in ATENDIMENTO_REMOTO:
            continue
        if _inteiro(linha.local) != LOCAL_PLATAFORMA:
            pontos.append(_ponto(
                "coer_remoto_plat",
                f"Na linha {linha.numero}, o atendimento foi remoto, então o "
                f"Local da Atividade deve ser {LOCAL_PLATAFORMA} (Plataforma).",
                linha=linha.numero, campo="local",
            ))
    return pontos


def coer_tnp(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Guia, seção 1.4: "Tempo não Produtivo é o produto." Vale para as
    classificações 18 e 20."""
    oficial = next(
        (p for p in base.valores_distintos("produto")
         if _normalizar(p) == "tempo nao produtivo"),
        None,
    )
    if oficial is None:
        return []

    pontos = []
    for linha in folha.linhas_em_uso:
        if _inteiro(linha.classificacao) not in CLASSIFICACOES_TNP_COM_PRODUTO_FIXO:
            continue
        if not linha.produto.tem_valor:
            continue
        if _normalizar(linha.produto.texto) != _normalizar(oficial):
            pontos.append(_ponto(
                "coer_tnp",
                f"Na linha {linha.numero}, a Classificação é "
                f"{linha.classificacao.texto} (TNP), então o produto deve ser "
                f"\"{oficial}\". O que aconteceu vai no Detalhamento.",
                linha=linha.numero, campo="produto",
            ))
    return pontos


# ==========================================================================
# PRODUTO
# ==========================================================================

# Guia, seção 1.2: estes quatro, escritos sozinhos, saíram do DE-PARA.
# É uma lista de proibições nomeada pelo Guia, não um domínio da base.
TERMOS_GENERICOS_PROIBIDOS = ("empréstimos", "financiamento", "investimento", "crédito")


def prod_sem_parenteses(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Guia, seção 1.3: os nomes dos produtos perderam os parênteses —
    "Crédito Pessoal", não "Crédito Pessoal (Emprestimo)"."""
    pontos = []
    for linha in folha.linhas_em_uso:
        texto = linha.produto.texto
        if linha.produto.tem_valor and ("(" in texto or ")" in texto):
            pontos.append(_ponto(
                "prod_sem_parenteses",
                f"Na linha {linha.numero}, escreva o produto sem os parênteses "
                "explicativos.",
                linha=linha.numero, campo="produto",
            ))
    return pontos


def prod_proibido_generico(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """Guia, seção 1.2: termo genérico sozinho volta como NOK.

    Só pega o termo SOZINHO. "Crédito Imobiliário" contém "Crédito" e é
    um produto legítimo — acusá-lo seria reprovar folha certa.
    """
    proibidos = {_normalizar(t) for t in TERMOS_GENERICOS_PROIBIDOS}
    pontos = []
    for linha in folha.linhas_em_uso:
        if not linha.produto.tem_valor:
            continue
        if _normalizar(linha.produto.texto) in proibidos:
            pontos.append(_ponto(
                "prod_proibido_generico",
                f"Na linha {linha.numero}, \"{linha.produto.texto}\" é um termo "
                "genérico. Procure no chatbot qual é o produto específico.",
                linha=linha.numero, campo="produto",
            ))
    return pontos


def _sem_parentese_final(texto: str) -> str:
    """ "Capital de Giro (Empréstimo)" -> "Capital de Giro". Guia 1.3: na
    folha o produto vai sem o parêntese explicativo."""
    return re.sub(r"\s*\([^)]*\)?\s*$", "", texto).strip()


def prod_depara(folha: Folha, base: BaseOficial) -> list[PontoParaRevisar]:
    """O produto escrito precisa existir na tabela oficial de atividades
    (28/09/2026), comparado sem acento, sem caixa e sem o parêntese final.

    Fora da tabela vira ALERTA, não erro: a letra à mão pode abreviar ou
    variar o nome, e reprovar folha certa é pior que pedir uma conferida.
    Termo genérico sozinho fica só com `prod_proibido_generico`.
    """
    aceitos = {
        _normalizar(n)
        for p in base.valores_distintos("produto")
        for n in (p, _sem_parentese_final(p))
    }
    genericos = {_normalizar(t) for t in TERMOS_GENERICOS_PROIBIDOS}
    pontos = []
    for linha in folha.linhas_em_uso:
        if not linha.produto.tem_valor:
            continue
        escrito = _normalizar(linha.produto.texto)
        if escrito in genericos:
            continue
        if escrito in aceitos or _normalizar(_sem_parentese_final(linha.produto.texto)) in aceitos:
            continue
        pontos.append(_ponto(
            "prod_depara",
            f"Na linha {linha.numero}, o produto \"{linha.produto.texto}\" não "
            "está na tabela oficial. Confira o nome no chatbot.",
            tipo=TipoPonto.ALERTA, linha=linha.numero, campo="produto",
        ))
    return pontos


# ==========================================================================
# ENTRE FOLHAS DO MESMO MAPEADO
# ==========================================================================

SEGUNDOS_ALVO = 8 * 3600
TOLERANCIA_SEGUNDOS = 15 * 60


def _mapeado_de(folha: Folha) -> tuple[str, str]:
    return (
        _normalizar(folha.cabecalho.nome.texto),
        _normalizar(folha.cabecalho.matricula.texto),
    )


def soma_por_mapeado(conjunto: Conjunto, base: BaseOficial) -> list[PontoParaRevisar]:
    """Manual, p. 37 e Guia, seção 1.5: trocou de mapeado, troca de
    folha — e o agrupamento do tempo é por mapeado, não por consultor.

    O que dá para verificar aqui: se as folhas que estão sendo somadas
    juntas são mesmo de uma pessoa só.
    """
    mapeados = {_mapeado_de(f) for f in conjunto.folhas}
    if len(mapeados) <= 1:
        return []
    return [_ponto(
        "soma_por_mapeado",
        "Estas folhas são de colaboradores mapeados diferentes. O tempo do dia "
        "é somado por mapeado — separe as folhas de cada um.",
    )]


def soma_8h(conjunto: Conjunto, base: BaseOficial) -> list[PontoParaRevisar]:
    """Manual, p. 37 e p. 56: o total cronometrado deve fechar 8 horas,
    com margem de 15 minutos para mais ou para menos.

    Não é avaliada quando o agrupamento está errado (somaria pessoas
    diferentes) nem quando algum tempo não foi lido com segurança
    (somaria um número incompleto sem avisar).
    """
    if len({_mapeado_de(f) for f in conjunto.folhas}) > 1:
        return []

    total = 0
    for folha in conjunto.folhas:
        for linha in folha.linhas_em_uso:
            for campo in ("hora", "minutos", "segundos"):
                celula = getattr(linha, campo)
                if not celula.tem_valor:
                    return []
                valor = _inteiro(celula)
                if valor is None:
                    return []
                total += valor * {"hora": 3600, "minutos": 60, "segundos": 1}[campo]

    if abs(total - SEGUNDOS_ALVO) <= TOLERANCIA_SEGUNDOS:
        return []

    horas, resto = divmod(total, 3600)
    return [_ponto(
        "soma_8h",
        f"O tempo total somado é {horas}h{resto // 60:02d}min. O dia de "
        "cronometragem deve fechar 8 horas, com margem de 15 minutos para mais "
        "ou para menos.",
    )]


# ==========================================================================
# Registro das regras
# ==========================================================================

REGRAS_DA_FOLHA = (
    leitura_incerta,
    cab_completo, cab_nome, cab_loja, cab_data_formato,
    linha_sem_brancos, linha_sequencial,
    sn_agenda, sn_venda, sn_ocorrencia,
    class_dominio, local_dominio, aten_dominio, clientes_dominio,
    tempo_minutos, tempo_segundos, quantidade_min,
    coer_segmento_m, coer_remoto_plat, coer_tnp,
    prod_sem_parenteses, prod_proibido_generico, prod_depara,
)

REGRAS_DO_CONJUNTO = (soma_por_mapeado, soma_8h)

# `leitura_incerta` não é do catálogo (é o mecanismo de confirmação do
# PRD, seções 6 e 8), por isso não entra nesta contagem.
REGRAS_DO_CATALOGO_APLICADAS = tuple(
    r.__name__ for r in REGRAS_DA_FOLHA if r is not leitura_incerta
)

# Regras do catálogo que NÃO rodam. Nenhuma foi completada por
# inferência — falta definição oficial, não código.
REGRAS_PENDENTES = {
    "cab_responsavel_id": (
        "Exige distinguir um ID de consultor de um nome de pessoa. O Manual "
        "(p. 44) manda usar o ID, mas não define o formato; os únicos exemplos "
        "no projeto são \"S07\" e \"S09\". Deduzir \"letra + dígitos\" de dois "
        "exemplos seria inventar o formato."
    ),
    "cab_troca_mapeado": (
        "FORA DO ESCOPO (decisão do usuário, 22/09/2026): vira orientação no "
        "guia dos consultores (trocou de mapeado -> folha nova), não regra. "
        "Exige saber que houve troca de colaborador mapeado durante o dia. Essa "
        "informação não está na folha: nenhuma coluna registra o mapeado por "
        "linha. Só seria verificável com um dado externo à folha."
    ),
}
