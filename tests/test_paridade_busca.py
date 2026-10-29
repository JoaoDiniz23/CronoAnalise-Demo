"""
O arquivo de paridade (Python → JavaScript offline) precisa refletir a
busca atual do backend. Se este teste falhar, rode
`scripts/gerar_paridade_busca.py` e depois `npm test`.
"""

import json

from scripts.gerar_paridade_busca import ARQUIVO, gerar


def test_arquivo_de_paridade_esta_atualizado():
    gravado = json.loads(ARQUIVO.read_text(encoding="utf-8"))
    assert gravado == gerar(), (
        "busca em Python mudou: rode scripts/gerar_paridade_busca.py e ajuste "
        "frontend/busca-local.js até `npm test` passar"
    )
