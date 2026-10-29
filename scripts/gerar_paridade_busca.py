"""
Gera `tests/dados_busca/paridade_busca.json`: o que a busca determinística
do backend (Python) devolve para um conjunto fixo de descrições.

`tests/busca-local.test.js` compara a cópia em JavaScript
(`frontend/busca-local.js`, usada offline no celular) contra este arquivo,
e `tests/test_paridade_busca.py` falha se ele ficar desatualizado em
relação ao Python. Mudou a busca em Python? Rode:

    venv\\Scripts\\python.exe scripts/gerar_paridade_busca.py

e ajuste o JavaScript até `npm test` passar.
"""

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from backend.busca.recuperador import RecuperadorLexical  # noqa: E402
from backend.busca.servico import (  # noqa: E402
    correspondencia_exata,
    correspondencia_por_nome,
    e_nome_de_produto,
)
from backend.busca.texto import CorretorDigitacao, radicais  # noqa: E402
from backend.dados import carregar_base_oficial  # noqa: E402

ARQUIVO = RAIZ / "tests" / "dados_busca" / "paridade_busca.json"

DESCRICOES = [
    "saque", "Saque", "SAQUE", "pix", "depósito", "câmbio", "TED", "treinamento",
    "Acompanhamento de metas", "contagem de numerario", "Contagem de numerários",
    "Gestão de equipe", "Oferta/Abertura", "Tempo não produtivo",
    "Pagamento de parcela Acordo (Dívida)", "Pagamento de parcela - Acordo (Dívida)",
    "Pagamento de parcela", "Dúvida/Ajuda e Suporte (cliente)", "cartão de crédito",
    "Numerários (dinheiro)", "Emissão de 2ª via de cartão", "segunda via do cartão",
    "segunda via do cartão de crédito", "2a via de fatura", "não foi saque",
    "cliente sacou dinheiro no caixa", "cliente sacou dinheiro usando o cartão no caixa",
    "Atendeu o cliente para tirar dúvida sobre empréstimo consignado.",
    "dúvida sobre consignado", "cliente consignado", "portabilidade de salário",
    "cliente trouxe a portabilidade do salário para o cliente",
    "cadastrou a senha nova do cartão de débito do cliente",
    "conferiu e organizou os malotes físicos da agência", "malote", "Malotes",
    "emitiu o recibo de pagamento de um boleto", "abriu uma conta corrente para um cliente novo",
    "abertura de conta", "cliente quer aumentar o limite", "cliente pagou a parcela do acordo",
    "transferiu dinheiro entre contas correntes", "consultou o limite do cartão de crédito",
    "cliente pedindo dinheiro para abrir um negócio", "fui almoçar no restaurante",
    "fazendo café na copa", "seguro de vida", "vendi seguro de vida",
    "funcionário indo abrir a loja no início do dia", "abrindo a agência",
    "gerente fechou a agência no fim do expediente", "conta aberta ontem",
    "Abertura do sistema no início da jornada", "Migração de conta entre agências",
    "Hoje de manhã, logo depois de abrir a agência, a gerente cadastrou a senha do "
    "cartão de débito de um senhor que estava com pressa",
    "de da do para", "",
    # erros de digitação (correção sem LLM)
    "acompanhamneto de metas", "acompanhamento de mteas", "contagen de numerarios",
    "sauqe", "sque", "depozito", "cartao de credtio", "portabilidae de salario",
    "emprestmo consignado", "treinamneto", "cambio", "fui almocar", "pixx", "almoço", "Almoco",
    "funcionario falando sobre cartão de crédito", "gerente conversou com cliente sobre saque",
    "disse que não quer o saque",
    "segudo de vida", "abertura de cnota corrente", "malottes",
]


def gerar() -> list[dict]:
    base = carregar_base_oficial()
    recuperador = RecuperadorLexical(base)
    corretor = CorretorDigitacao(
        t for a in base.listar_atividades() for t in (a.atividade, a.produto, a.subgrupo)
    )
    casos = []
    for texto in DESCRICOES:
        exata = correspondencia_exata(texto, base) if radicais(texto) else None
        casos.append(
            {
                "texto": texto,
                "corrigido": corretor.corrigir(texto),
                "radicais": radicais(texto),
                "exata": exata.id if exata else None,
                "por_nome": [a.id for a in correspondencia_por_nome(texto, base)],
                "nome_de_produto": e_nome_de_produto(texto, base),
                "candidatos": [
                    {"id": c.atividade.id, "pontuacao": c.pontuacao, "termos": c.termos_casados}
                    for c in recuperador.buscar(texto, 10)
                ],
            }
        )
    return casos


if __name__ == "__main__":
    ARQUIVO.write_text(
        json.dumps(gerar(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"gravado: {ARQUIVO.relative_to(RAIZ)}")
