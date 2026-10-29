"""
Avaliação da busca de atividades contra os casos de
`tests/dados_busca/casos_avaliacao.json` (gerais) e
`tests/dados_busca/casos_desambiguacao.json` (atividades de nome parecido,
29/09/2026 — grupos "dev" e "reserva"; `--grupo` escolhe).

Sem argumentos, mede só a recuperação (etapa A), sem rede e sem custo:
para cada caso, se alguma atividade aceita apareceu entre os candidatos.

Com --llm, roda a busca completa com o LLM real (Claude) (UMA chamada por caso
que chegue ao LLM — cuidado com a quota) e compara o resultado final.

Espaçamento entre chamadas: ninguém confirmou ainda o RPM (limite de
requisições por minuto) da conta paga, então por padrão o script espera
`--intervalo-s` segundos entre um caso que chamou o LLM e o próximo — nunca
depois de um caso resolvido sem rede (`correspondencia_exata`/sem
candidatos). Ajustável por `--intervalo-s 0` se algum dia o RPM real for
confirmado alto o bastante para dispensar isso.

Uso:
    .venv\\Scripts\\python.exe scripts\\avaliar_busca.py
    .venv\\Scripts\\python.exe scripts\\avaliar_busca.py --llm
    .venv\\Scripts\\python.exe scripts\\avaliar_busca.py --llm --intervalo-s 6
"""

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from backend.busca import RecuperadorLexical, StatusBusca, criar_buscador  # noqa: E402
from backend.busca.modelos import Origem  # noqa: E402
from backend.dados import BaseOficial, carregar_base_oficial  # noqa: E402

# Intervalo padrão entre chamadas reais ao LLM, em segundos. Conservador
# de propósito: sem o RPM confirmado da conta, é melhor um script lento do
# que um 429 por limite de requisições por minuto (que hoje sobe direto,
# sem retry — ver backend/busca/llm.py, decisão deliberada).
INTERVALO_PADRAO_S = 4.0

ARQUIVO_CASOS = RAIZ / "tests" / "dados_busca" / "casos_avaliacao.json"
ARQUIVO_DESAMBIGUACAO = RAIZ / "tests" / "dados_busca" / "casos_desambiguacao.json"


def carregar_casos(base: BaseOficial, grupo: str = "todos") -> list[dict]:
    """Lê os casos e resolve cada par aceito para ID. Falha se algum par
    não existir na base — caso de avaliação quebrado não passa calado.
    `grupo`: "todos", "gerais" (casos_avaliacao), "dev", "reserva" ou "campo" (casos reais de 05/10)."""
    por_chave = {(a.atividade, a.produto): a.id for a in base.listar_atividades()}
    gerais = json.loads(ARQUIVO_CASOS.read_text(encoding="utf-8"))["casos"]
    for caso in gerais:
        caso["grupo"] = "gerais"
    dificeis = json.loads(ARQUIVO_DESAMBIGUACAO.read_text(encoding="utf-8"))["casos"]
    casos = [c for c in gerais + dificeis if grupo in ("todos", c["grupo"])]
    for caso in casos:
        faltando = [par for par in caso["aceitas"] if tuple(par) not in por_chave]
        if faltando:
            raise SystemExit(f"caso {caso['texto']!r}: pares fora da base oficial: {faltando}")
        caso["ids_aceitos"] = {por_chave[tuple(par)] for par in caso["aceitas"]}
    return casos


def classificar(caso: dict, resultado) -> str:
    """certo | ambigua_com_certo | sem_resposta | errado. "errado" = escolheu
    (ou só ofereceu) atividade que não serve — o que nunca pode acontecer."""
    if acertou(caso, resultado):
        return "certo"
    if caso["esperado"] != "encontrada":
        return "errado"
    if resultado.status == StatusBusca.AMBIGUA:
        ofertas = {a.id for a in resultado.alternativas}
        return "ambigua_com_certo" if ofertas & caso["ids_aceitos"] else "errado"
    if resultado.status == StatusBusca.ENCONTRADA:
        return "errado"
    return "sem_resposta"


def acertou(caso: dict, resultado) -> bool:
    if caso["esperado"] == "encontrada":
        return (
            resultado.status == StatusBusca.ENCONTRADA
            and resultado.atividade.id in caso["ids_aceitos"]
        )
    return resultado.status in (StatusBusca.AMBIGUA, StatusBusca.SEM_CORRESPONDENCIA)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="chama o LLM real")
    parser.add_argument("--limite", type=int, default=10, help="candidatos por busca")
    parser.add_argument(
        "--intervalo-s",
        type=float,
        default=INTERVALO_PADRAO_S,
        help=f"segundos de espera entre chamadas reais ao LLM (padrão: {INTERVALO_PADRAO_S:g})",
    )
    parser.add_argument(
        "--grupo", default="todos", choices=["todos", "gerais", "dev", "reserva", "campo"],
        help="quais casos rodar (padrão: todos)",
    )
    args = parser.parse_args()

    base = carregar_base_oficial()
    casos = carregar_casos(base, args.grupo)
    recuperador = RecuperadorLexical(base)

    print(f"== Recuperação (top {args.limite}) ==")
    com_alvo = [c for c in casos if c["esperado"] == "encontrada"]
    recuperados = 0
    for caso in com_alvo:
        ids = [c.atividade.id for c in recuperador.buscar(caso["texto"], args.limite)]
        posicoes = [ids.index(i) + 1 for i in caso["ids_aceitos"] if i in ids]
        ok = bool(posicoes)
        recuperados += ok
        onde = f"posição {min(posicoes)}" if ok else "NÃO recuperada"
        print(f"  [{'ok' if ok else '--'}] {caso['texto']!r}: {onde}")
    print(f"  recall@{args.limite}: {recuperados}/{len(com_alvo)}")

    if not args.llm:
        return

    print("\n== Busca completa com LLM ==")
    if args.intervalo_s > 0:
        print(f"  (aguardando {args.intervalo_s:g}s entre casos que chamarem o LLM — RPM não confirmado)")
    buscador = criar_buscador(base)
    buscador.limite_candidatos = args.limite
    acertos = 0
    chamadas_ao_llm = 0
    placar: dict[str, int] = {}
    for caso in casos:
        resultado = buscador.buscar(caso["texto"])

        # Só chamou o LLM de verdade se não foi resolvido por
        # correspondência exata nem descartado por falta de candidato —
        # os dois casos saem com origem=BUSCA sem gastar rede. Um caso que
        # chamou e falhou (erro preenchido) também conta: gastou a chamada.
        chamou_o_llm = resultado.origem != Origem.BUSCA and resultado.status != StatusBusca.ENTRADA_INSUFICIENTE
        if chamou_o_llm:
            chamadas_ao_llm += 1

        ok = acertou(caso, resultado)
        acertos += ok
        classe = classificar(caso, resultado)
        placar[classe] = placar.get(classe, 0) + 1
        escolha = (
            f"#{resultado.atividade.id} {resultado.atividade.atividade} | {resultado.atividade.produto}"
            if resultado.atividade else ""
        )
        erro = f" erro={resultado.erro.tipo}" if resultado.erro else ""
        print(
            f"  [{'ok' if ok else '--'}] ({classe}) {caso['texto']!r}\n"
            f"       status={resultado.status.value} origem={resultado.origem and resultado.origem.value}"
            f"{erro} {escolha}\n"
            f"       justificativa={resultado.justificativa!r}"
        )

        if chamou_o_llm and args.intervalo_s > 0 and caso is not casos[-1]:
            time.sleep(args.intervalo_s)

    print(f"  acertos: {acertos}/{len(casos)} (modelo {buscador.cliente_llm.modelo})")
    print(f"  placar: {placar}")
    print(f"  chamadas reais ao LLM: {chamadas_ao_llm}/{len(casos)}")


if __name__ == "__main__":
    main()
