"""
Relatório de consistência da base oficial do cliente.

Somente leitura — este script NÃO altera nenhum dado. Ele confere a
integridade da base, confirma que as regras de classificação já acertadas
continuam valendo, e lista as divergências que precisam ser levadas ao
cliente (não corrigidas no código).

Rodar sempre que a base for atualizada, e principalmente quando a tabela
oficial nova chegar.

Uso:
    venv\\Scripts\\python.exe scripts\\verificar_base_oficial.py
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding="utf-8")

from backend.dados import carregar_base_oficial  # noqa: E402

HTML_ORIGEM = RAIZ / "conteúdos importantes" / "Chatbot.html"

CATEGORIA_DO_PREFIXO = {"C": "comercial", "O": "operacional", "TNP": "tnp"}


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", str(texto).lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def secao(titulo: str) -> None:
    print(f"\n=== {titulo} ===")


def verificar_origem(base) -> list[str]:
    """A base em dados/ deve continuar idêntica à origem embutida no HTML."""
    achados = []
    if not HTML_ORIGEM.is_file():
        return [f"[?] origem não encontrada: {HTML_ORIGEM}"]

    encontrado = re.search(
        r"const DADOS = (\[.*?\]);", HTML_ORIGEM.read_text(encoding="utf-8"), re.DOTALL
    )
    if not encontrado:
        return ["[?] não encontrei 'const DADOS' no HTML de origem"]

    origem = json.loads(encontrado.group(1))
    atual = [
        a.model_dump(
            include={
                "id", "atividade", "produto", "subgrupo",
                "clientes", "segmento", "atendimento", "classificacao",
            }
        )
        for a in base.listar_atividades()
    ]
    igual = origem == atual
    achados.append(
        f"[{'OK' if igual else 'DIVERGE'}] dados/ idêntico à origem no Chatbot.html "
        f"({len(origem)} registros na origem)"
    )
    return achados


def correspondencia_subgrupo_codigo(base) -> tuple[list[str], list[str]]:
    """Aproxima subgrupos da base aos códigos da legenda por nome.

    IMPORTANTE: isto é uma observação calculada, NÃO um DE-PARA oficial.
    Serve para mostrar o que bate e, principalmente, o que NÃO bate.
    """
    linhas, pendencias = [], []
    subgrupos = base.valores_distintos("subgrupo")
    pares: dict[str, tuple[int, str] | None] = {}

    for subgrupo in subgrupos:
        nome_sub, _, categoria_sub = subgrupo.rpartition(" + ")
        par = None
        for codigo in base.codigos_classificacao():
            descricao = base.descricao_classificacao(codigo)
            prefixo, _, nome_cod = descricao.partition(": ")
            if CATEGORIA_DO_PREFIXO.get(prefixo) != normalizar(categoria_sub):
                continue
            a, b = normalizar(nome_sub), normalizar(nome_cod)
            if a == b or a.startswith(b[:18]) or b.startswith(a[:18]):
                par = (codigo, descricao)
                break
        pares[subgrupo] = par
        linhas.append(f"  {subgrupo[:58]:<58} -> {par[0] if par else '??'}")

    sem_par = [s for s, p in pares.items() if p is None]
    usados = {p[0] for p in pares.values() if p}
    codigos_sem_subgrupo = sorted(set(base.codigos_classificacao()) - usados)

    for subgrupo in sem_par:
        pendencias.append(
            f"[PENDENTE] subgrupo '{subgrupo}' não casou com nenhum código da legenda"
        )
    for codigo in codigos_sem_subgrupo:
        pendencias.append(
            f"[PENDENTE] código {codigo} ('{base.descricao_classificacao(codigo)}') "
            "não tem subgrupo correspondente na base de atividades"
        )
    return linhas, pendencias


def grafias_divergentes(base) -> list[str]:
    """Valores que só diferem por acento/caixa são provável erro de digitação
    na fonte oficial — reportar, nunca corrigir automaticamente."""
    pendencias = []
    for campo in ("clientes", "segmento", "atendimento", "classificacao"):
        agrupado: dict[str, set[str]] = {}
        for valor in base.valores_distintos(campo):
            agrupado.setdefault(normalizar(valor), set()).add(valor)
        for variantes in agrupado.values():
            if len(variantes) > 1:
                pendencias.append(
                    f"[PENDENTE] campo '{campo}' tem grafias diferentes para o mesmo "
                    f"valor: {sorted(variantes)}"
                )
    return pendencias


def main() -> None:
    base = carregar_base_oficial()
    pendencias: list[str] = []

    secao("Integridade da base")
    atividades = base.listar_atividades()
    ids = [a.id for a in atividades]
    chaves = {(a.atividade, a.produto) for a in atividades}
    print(f"[OK] {len(atividades)} atividades carregadas e validadas")
    print(f"[{'OK' if len(set(ids)) == len(ids) else 'FALHOU'}] ids únicos")
    print(f"[{'OK' if len(chaves) == len(atividades) else 'FALHOU'}] par (atividade, produto) único")
    print(f"[OK] {len(base.valores_distintos('atividade'))} atividades distintas, "
          f"{len(base.valores_distintos('produto'))} produtos distintos")
    for linha in verificar_origem(base):
        print(linha)

    secao("Regras de classificação já confirmadas")
    codigos = base.codigos_classificacao()
    print(f"[OK] códigos oficiais: {codigos}")
    print(f"[{'OK' if 8 in codigos else 'FALHOU'}] código 8 presente: "
          f"{base.descricao_classificacao(8)}")
    print(f"[{'OK' if 20 in codigos else 'FALHOU'}] código 20 presente: "
          f"{base.descricao_classificacao(20)}")
    print(f"[{'OK' if 7 not in codigos else 'FALHOU'}] código 7 ausente "
          "(molde oficial pula de 6 para 8)")

    secao("Correspondência subgrupo <-> código (CALCULADA, não oficial)")
    linhas, pend_corresp = correspondencia_subgrupo_codigo(base)
    print("\n".join(linhas))
    pendencias += pend_corresp

    secao("Grafias divergentes dentro da própria base")
    pend_grafia = grafias_divergentes(base)
    print("\n".join(pend_grafia) if pend_grafia else "[OK] nenhuma encontrada")
    pendencias += pend_grafia

    secao("Legendas sem fonte oficial")
    if base.segmento_legenda is None:
        print("[PENDENTE] Segmento não tem legenda oficial carregada")
        pendencias.append("[PENDENTE] Segmento sem legenda oficial")
    else:
        siglas = len(base.segmento_legenda)
        valores = len(base.valores_distintos("segmento"))
        print(f"[OK] legenda oficial de Segmento carregada do molde: {siglas} siglas")
        if siglas != valores:
            print(f"[PENDENTE] a legenda tem {siglas} siglas e o campo `segmento` da "
                  f"base tem {valores} valores; o DE-PARA entre os dois não foi "
                  "confirmado pelo cliente e não é feito por inferência")
            pendencias.append(
                f"[PENDENTE] DE-PARA sigla de Segmento ({siglas}) x valores da base "
                f"({valores}) não confirmado"
            )

    secao(f"Resumo: {len(pendencias)} ponto(s) dependem de confirmação do cliente")
    for p in pendencias:
        print(p)


if __name__ == "__main__":
    main()
