"""
Construtores de folha para os testes: uma folha sem nenhum problema
conhecido, que cada teste estraga num ponto so.

Estava dentro de `test_folha_regras.py`; virou modulo proprio quando os
testes de `backend/analise/` passaram a precisar das mesmas folhas. Uma
copia em cada arquivo significaria duas folhas "corretas" que poderiam
divergir sem ninguem perceber -- e um teste que passa porque a folha de
apoio mudou nao prova nada.

Nenhum valor aqui vem de folha real de pessoa nenhuma: sao dados
inventados neste arquivo, no formato que o Manual descreve.
"""

from backend.folha import Cabecalho, Celula, Folha, Linha


def _celula(valor) -> Celula:
    """Aceita texto, ou uma Celula ja pronta (para vazia/ilegivel)."""
    return valor if isinstance(valor, Celula) else Celula.lida(valor)


def cab(**troca) -> Cabecalho:
    campos = {
        "data": "13/08",
        "uniorg": "1234567",
        "loja": "JARDIM DAS FLORES",
        "nome": "ANA SOUZA",
        "matricula": "T556714",
        "cargo": "Caixa",
        "id_responsavel": "S09",
        "numero_folha": "1",
    }
    campos.update(troca)
    return Cabecalho(**{k: _celula(v) for k, v in campos.items()})


def linha(numero: int = 1, **troca) -> Linha:
    campos = {
        "num_processo": "1.1",
        "detalhamento": "REATIVACAO",
        "produto": "Conta Corrente",
        "segmento": "ES",
        "agenda_certo": "N",
        "classificacao": "1",
        "local": "2",
        "atendimento": "5",
        "clientes": "1",
        "venda_concluida": "S",
        "hora": "0",
        "minutos": "10",
        "segundos": "5",
        "quantidade": "1",
        "ocorrencia": "N",
    }
    campos.update(troca)
    return Linha(numero=numero, **{k: _celula(v) for k, v in campos.items()})


def folha(linhas=None, **troca_cab) -> Folha:
    return Folha(cabecalho=cab(**troca_cab), linhas=linhas or [linha(1), linha(2)])


def regras_acionadas(resultado) -> set[str]:
    return {p.regra for p in resultado.pontos_para_revisar}


def linha_8h(numero: int = 1, **troca) -> Linha:
    """Linha cujo tempo fecha o dia inteiro do mapeado.

    `soma_8h` e uma regra de CONJUNTO: ela dispara sempre que o total das
    fichas nao fecha 8 horas. A folha de apoio padrao soma ~20 minutos,
    entao qualquer teste que afirme "nenhum ponto" precisa de uma linha
    assim -- senao o apontamento de soma entra junto e esconde o que o
    teste queria mostrar.
    """
    campos = {"hora": "8", "minutos": "0", "segundos": "0"}
    campos.update(troca)
    return linha(numero, **campos)


def folha_de_oito_horas(horas: int = 8, linhas=None, **troca_cab) -> Folha:
    """Uma folha cujo tempo total fecha exatamente o dia do mapeado."""
    return Folha(
        cabecalho=cab(**troca_cab),
        linhas=linhas
        or [linha(1, hora=str(horas), minutos="0", segundos="0")],
    )
