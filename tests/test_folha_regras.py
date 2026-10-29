"""
Testes do motor deterministico de validacao da folha de coleta.

O motor recebe dados JA ESTRUTURADOS e nao sabe de onde eles vieram
(foto, OCR, LLM, digitacao). Por isso estes testes nao usam rede, nem
imagem, nem arquivo de folha - so objetos montados aqui.

O catalogo de regras vem de `docs/historico/prd_validador_folhas.md`,
secao 7.5, que cita a fonte documental de cada regra (Manual de Coleta e
Guia de atualizacao). Nenhuma regra nova foi criada aqui.
"""

import pytest

from backend.dados import carregar_base_oficial
from backend.folha import regras
from backend.folha import (
    Celula,
    Conjunto,
    EstadoLeitura,
    Folha,
    Linha,
    TipoPonto,
    validar_conjunto,
    validar_folha,
)


@pytest.fixture(scope="module")
def base():
    return carregar_base_oficial()


# --------------------------------------------------------------------------
# Construtores de apoio: uma folha sem nenhum problema conhecido.
# Cada teste sobrescreve UM campo, para provar que o ponto apontado vem
# da regra em teste e nao de outra.
#
# Moveram-se para `tests/apoio_folha.py` quando os testes de
# `backend/analise/` passaram a precisar das mesmas folhas -- duas copias
# poderiam divergir sem ninguem perceber.
# --------------------------------------------------------------------------

from apoio_folha import cab, folha, linha, regras_acionadas  # noqa: E402


# --------------------------------------------------------------------------
# Folha sem problemas
# --------------------------------------------------------------------------

def test_folha_sem_problemas_nao_gera_pontos_para_revisar(base):
    resultado = validar_folha(folha(), base)

    assert resultado.pontos_para_revisar == []
    assert resultado.sem_pontos_para_revisar


def test_ausencia_de_pontos_nao_e_certificacao_de_folha_correta(base):
    # CLAUDE.md: o produto aponta pontos para revisar e NUNCA certifica a
    # folha. O resultado nao pode expor nada que signifique "aprovada".
    resultado = validar_folha(folha(), base)

    assert not hasattr(resultado, "valida")
    assert not hasattr(resultado, "aprovada")
    assert "nunca" in type(resultado).__doc__.lower()


def test_resultado_declara_as_regras_que_rodaram_e_as_pendentes(base):
    resultado = validar_folha(folha(), base)

    assert "class_dominio" in resultado.regras_aplicadas
    assert "cab_loja" in resultado.regras_aplicadas
    assert "cab_responsavel_id" in resultado.regras_pendentes


# --------------------------------------------------------------------------
# CABECALHO
# --------------------------------------------------------------------------

def test_cab_completo_aceita_cabecalho_inteiro_preenchido(base):
    assert "cab_completo" not in regras_acionadas(validar_folha(folha(), base))


def test_cab_completo_acusa_matricula_em_branco(base):
    # Manual, p. 44: "MATRICULA E CARGO NAO podem ser esquecidas".
    resultado = validar_folha(folha(matricula=Celula.vazia()), base)

    assert "cab_completo" in regras_acionadas(resultado)
    ponto = next(p for p in resultado.pontos_para_revisar if p.regra == "cab_completo")
    assert ponto.campo == "matricula"
    assert ponto.linha is None


def test_cab_completo_acusa_cargo_em_branco(base):
    resultado = validar_folha(folha(cargo=Celula.vazia()), base)

    assert "cab_completo" in regras_acionadas(resultado)


def test_cab_nome_aceita_nome_e_sobrenome(base):
    assert "cab_nome" not in regras_acionadas(validar_folha(folha(), base))


def test_cab_nome_acusa_apenas_o_primeiro_nome(base):
    # Manual, p. 44: "NOME + SOBRENOME (do mapeado)".
    resultado = validar_folha(folha(nome="ANA"), base)

    assert "cab_nome" in regras_acionadas(resultado)


@pytest.mark.parametrize("loja", ["JARDIM DAS FLORES", "Vila Nova", "shopping norte.", "Avenida  Principal"])
def test_cab_loja_aceita_loja_da_lista_com_acento_caixa_e_pontuacao(base, loja):
    assert "cab_loja" not in regras_acionadas(validar_folha(folha(loja=loja), base))


@pytest.mark.parametrize("loja", ["UNIVERSAL", "DIGITAL", "EMPRESAS"])
def test_cab_loja_alerta_tipo_de_loja_ou_nome_fora_da_lista(base, loja):
    resultado = validar_folha(folha(loja=loja), base)
    pontos = [p for p in resultado.pontos_para_revisar if p.regra == "cab_loja"]
    assert [p.tipo for p in pontos] == [TipoPonto.ALERTA]


def test_cab_data_formato_aceita_dia_barra_mes(base):
    assert "cab_data_formato" not in regras_acionadas(validar_folha(folha(), base))


def test_cab_data_formato_recusa_data_com_ano(base):
    # Manual, p. 44: "Data SEMPRE no formato dia/mes (sem colocar o ano)".
    resultado = validar_folha(folha(data="13/08/2026"), base)

    assert "cab_data_formato" in regras_acionadas(resultado)


def test_cab_data_formato_recusa_mes_inexistente(base):
    assert "cab_data_formato" in regras_acionadas(validar_folha(folha(data="13/13"), base))


def test_cab_data_formato_nao_acusa_formato_quando_a_data_esta_vazia(base):
    # Campo vazio e problema do cab_completo. Duas queixas para o mesmo
    # campo confundem o consultor.
    resultado = validar_folha(folha(data=Celula.vazia()), base)

    assert "cab_completo" in regras_acionadas(resultado)
    assert "cab_data_formato" not in regras_acionadas(resultado)


# --------------------------------------------------------------------------
# LINHA A LINHA
# --------------------------------------------------------------------------

def test_linha_sem_brancos_aceita_linha_completa(base):
    assert "linha_sem_brancos" not in regras_acionadas(validar_folha(folha(), base))


def test_linha_sem_brancos_acusa_campo_vazio_no_meio_da_linha(base):
    # Manual, p. 43: "Nao deixe valores em branco. Sempre preencha todos
    # os campos."
    resultado = validar_folha(folha([linha(1, produto=Celula.vazia())]), base)

    assert "linha_sem_brancos" in regras_acionadas(resultado)
    ponto = next(
        p for p in resultado.pontos_para_revisar if p.regra == "linha_sem_brancos"
    )
    assert ponto.linha == 1
    assert ponto.campo == "produto"


def test_linha_totalmente_vazia_nao_e_acusada_de_ter_brancos(base):
    # Folha de 15 linhas quase nunca e usada inteira. Linha nao usada nao
    # e erro; linha usada pela metade e.
    vazia = Linha(
        numero=2,
        **{campo: Celula.vazia() for campo in Linha.CAMPOS},
    )
    resultado = validar_folha(folha([linha(1), vazia]), base)

    assert resultado.pontos_para_revisar == []


def test_linha_sequencial_aceita_linhas_1_a_3(base):
    resultado = validar_folha(folha([linha(1), linha(2), linha(3)]), base)

    assert "linha_sequencial" not in regras_acionadas(resultado)


def test_linha_sequencial_acusa_linha_pulada(base):
    vazia = Linha(numero=2, **{c: Celula.vazia() for c in Linha.CAMPOS})
    resultado = validar_folha(folha([linha(1), vazia, linha(3)]), base)

    assert "linha_sequencial" in regras_acionadas(resultado)


@pytest.mark.parametrize(
    "regra,campo",
    [
        ("sn_agenda", "agenda_certo"),
        ("sn_venda", "venda_concluida"),
        ("sn_ocorrencia", "ocorrencia"),
    ],
)
def test_campos_s_ou_n_aceitam_s_e_n(base, regra, campo):
    for valor in ("S", "N"):
        resultado = validar_folha(folha([linha(1, **{campo: valor})]), base)
        assert regra not in regras_acionadas(resultado)


@pytest.mark.parametrize(
    "regra,campo",
    [
        ("sn_agenda", "agenda_certo"),
        ("sn_venda", "venda_concluida"),
        ("sn_ocorrencia", "ocorrencia"),
    ],
)
def test_campos_s_ou_n_recusam_sim_por_extenso(base, regra, campo):
    # Manual, p. 43, exemplo incorreto: "SIM" escrito onde cabe "S".
    resultado = validar_folha(folha([linha(1, **{campo: "SIM"})]), base)

    assert regra in regras_acionadas(resultado)


def test_campo_s_ou_n_aceita_minuscula(base):
    # A folha e preenchida em letra bastao; a caixa da letra nao e o dado.
    assert "sn_agenda" not in regras_acionadas(
        validar_folha(folha([linha(1, agenda_certo="s")]), base)
    )


@pytest.mark.parametrize(
    "regra,campo,valido,invalido",
    [
        ("class_dominio", "classificacao", "8", "7"),
        ("local_dominio", "local", "8", "7"),
        ("aten_dominio", "atendimento", "6", "9"),
        ("clientes_dominio", "clientes", "5", "6"),
    ],
)
def test_colunas_de_dominio_fechado(base, regra, campo, valido, invalido):
    ok = validar_folha(folha([linha(1, **{campo: valido})]), base)
    assert regra not in regras_acionadas(ok)

    ruim = validar_folha(folha([linha(1, **{campo: invalido})]), base)
    assert regra in regras_acionadas(ruim)


def test_class_dominio_recusa_o_codigo_7_que_nao_existe_na_folha(base):
    # Guia, secao 2.1: o 7 nao existe justamente para nao virar 1 na
    # leitura. Um 7 lido e sempre problema.
    resultado = validar_folha(folha([linha(1, classificacao="7")]), base)

    ponto = next(p for p in resultado.pontos_para_revisar if p.regra == "class_dominio")
    assert ponto.linha == 1
    assert ponto.campo == "classificacao"


def test_dominio_fechado_recusa_texto_no_lugar_do_codigo(base):
    # Manual, p. 43, exemplo incorreto: "PF" escrito na coluna Clientes,
    # que e numerica.
    resultado = validar_folha(folha([linha(1, clientes="PF")]), base)

    assert "clientes_dominio" in regras_acionadas(resultado)


@pytest.mark.parametrize("campo,regra", [("minutos", "tempo_minutos"), ("segundos", "tempo_segundos")])
def test_minutos_e_segundos_aceitam_0_a_59(base, campo, regra):
    for valor in ("0", "59"):
        resultado = validar_folha(folha([linha(1, **{campo: valor})]), base)
        assert regra not in regras_acionadas(resultado)


@pytest.mark.parametrize("campo,regra", [("minutos", "tempo_minutos"), ("segundos", "tempo_segundos")])
def test_minutos_e_segundos_recusam_60(base, campo, regra):
    resultado = validar_folha(folha([linha(1, **{campo: "60"})]), base)

    assert regra in regras_acionadas(resultado)


def test_quantidade_min_aceita_1(base):
    assert "quantidade_min" not in regras_acionadas(validar_folha(folha(), base))


def test_quantidade_min_recusa_zero(base):
    assert "quantidade_min" in regras_acionadas(
        validar_folha(folha([linha(1, quantidade="0")]), base)
    )


# --------------------------------------------------------------------------
# COERENCIA DENTRO DA LINHA
# --------------------------------------------------------------------------

def test_coer_segmento_m_aceita_mei_com_cliente_pj(base):
    resultado = validar_folha(folha([linha(1, segmento="MEI", clientes="2")]), base)

    assert "coer_segmento_m" not in regras_acionadas(resultado)


def test_coer_segmento_m_acusa_mei_com_cliente_pf(base):
    # Regra fictícia da demo: MEI é sempre Cliente PJ.
    resultado = validar_folha(folha([linha(1, segmento="MEI", clientes="1")]), base)

    assert "coer_segmento_m" in regras_acionadas(resultado)


def test_coer_remoto_plat_aceita_atendimento_remoto_na_plataforma(base):
    resultado = validar_folha(folha([linha(1, atendimento="2", local="4")]), base)

    assert "coer_remoto_plat" not in regras_acionadas(resultado)


def test_coer_remoto_plat_acusa_atendimento_remoto_fora_da_plataforma(base):
    # Guia, secao 2.1: atendimento remoto tem local 4, porque e de la que
    # o especialista atendeu.
    resultado = validar_folha(folha([linha(1, atendimento="2", local="2")]), base)

    assert "coer_remoto_plat" in regras_acionadas(resultado)


def test_coer_remoto_plat_nao_se_aplica_a_atendimento_presencial(base):
    resultado = validar_folha(folha([linha(1, atendimento="5", local="2")]), base)

    assert "coer_remoto_plat" not in regras_acionadas(resultado)


def test_coer_tnp_aceita_classificacao_18_com_produto_tempo_nao_produtivo(base):
    resultado = validar_folha(
        folha([linha(1, classificacao="18", produto="TEMPO NAO PRODUTIVO",
                     detalhamento="ALMOCO")]),
        base,
    )

    assert "coer_tnp" not in regras_acionadas(resultado)


def test_coer_tnp_acusa_classificacao_20_com_outro_produto(base):
    # Guia, secao 1.4: "Tempo nao Produtivo e o produto."
    resultado = validar_folha(folha([linha(1, classificacao="20", produto="Conta Corrente")]), base)

    assert "coer_tnp" in regras_acionadas(resultado)


def test_coer_tnp_nao_se_aplica_a_classificacao_comercial(base):
    assert "coer_tnp" not in regras_acionadas(validar_folha(folha(), base))


# --------------------------------------------------------------------------
# PRODUTO
# --------------------------------------------------------------------------

def test_prod_sem_parenteses_aceita_produto_sem_parenteses(base):
    assert "prod_sem_parenteses" not in regras_acionadas(validar_folha(folha(), base))


def test_prod_sem_parenteses_acusa_produto_com_parenteses(base):
    # Guia, secao 1.3: escreve "Credito Pessoal", nao "Credito Pessoal
    # (Emprestimo)".
    resultado = validar_folha(
        folha([linha(1, produto="Crédito Pessoal (Emprestimo)")]), base
    )

    assert "prod_sem_parenteses" in regras_acionadas(resultado)


def test_prod_proibido_generico_aceita_produto_especifico(base):
    resultado = validar_folha(folha([linha(1, produto="Crédito Pessoal")]), base)

    assert "prod_proibido_generico" not in regras_acionadas(resultado)


@pytest.mark.parametrize(
    "generico", ["Empréstimos", "Financiamento", "Investimento", "Crédito"]
)
def test_prod_proibido_generico_recusa_os_quatro_termos_do_guia(base, generico):
    # Guia, secao 1.2: esses quatro sozinhos sairam do DE-PARA.
    resultado = validar_folha(folha([linha(1, produto=generico)]), base)

    assert "prod_proibido_generico" in regras_acionadas(resultado)


def test_prod_proibido_generico_nao_pega_o_termo_dentro_de_um_nome_maior(base):
    # "Credito Pessoal" contem "Credito", mas nao e o termo generico
    # sozinho - proibir isso seria acusar a folha certa.
    resultado = validar_folha(folha([linha(1, produto="Crédito Imobiliário")]), base)

    assert "prod_proibido_generico" not in regras_acionadas(resultado)


def test_prod_depara_aceita_produto_da_tabela_oficial(base):
    resultado = validar_folha(folha([linha(1, produto="Confirming")]), base)

    assert "prod_depara" not in regras_acionadas(resultado)


def test_prod_depara_aceita_produto_sem_o_parentese_e_sem_acento(base):
    # Na tabela: "Capital de Giro (Empréstimo)". Guia 1.3 manda escrever
    # sem o parentese; letra bastao nao tem acento.
    resultado = validar_folha(folha([linha(1, produto="CAPITAL DE GIRO")]), base)

    assert "prod_depara" not in regras_acionadas(resultado)


def test_prod_depara_aceita_o_nome_completo_com_parentese(base):
    # O parentese ja e cobrado por prod_sem_parenteses; aqui nao duplica.
    resultado = validar_folha(
        folha([linha(1, produto="Capital de Giro (Empréstimo)")]), base
    )

    assert "prod_depara" not in regras_acionadas(resultado)


def test_prod_depara_produto_fora_da_tabela_vira_alerta_nao_erro(base):
    resultado = validar_folha(folha([linha(1, produto="Produto Inexistente XYZ")]), base)

    pontos = [p for p in resultado.pontos_para_revisar if p.regra == "prod_depara"]
    assert len(pontos) == 1
    assert pontos[0].tipo == TipoPonto.ALERTA
    assert pontos[0].linha == 1


def test_prod_depara_nao_repete_o_termo_generico(base):
    # "Empréstimos" ja e acusado por prod_proibido_generico.
    resultado = validar_folha(folha([linha(1, produto="Empréstimos")]), base)

    assert "prod_depara" not in regras_acionadas(resultado)


def test_prod_depara_saiu_das_pendentes(base):
    resultado = validar_folha(folha(), base)

    assert "prod_depara" in resultado.regras_aplicadas
    assert "prod_depara" not in resultado.regras_pendentes


# --------------------------------------------------------------------------
# ESTADOS DE LEITURA
# --------------------------------------------------------------------------

def test_celula_ilegivel_nao_e_tratada_como_vazia(base):
    # O ponto mais importante do modelo: "nao consegui ler" e "o consultor
    # deixou em branco" tem tratamentos opostos.
    resultado = validar_folha(folha([linha(1, classificacao=Celula.ilegivel())]), base)

    acionadas = regras_acionadas(resultado)
    assert "linha_sem_brancos" not in acionadas
    assert "class_dominio" not in acionadas
    assert "leitura_incerta" in acionadas


def test_celula_ilegivel_pede_confirmacao_e_nao_vira_erro(base):
    resultado = validar_folha(folha([linha(1, classificacao=Celula.ilegivel())]), base)

    ponto = next(
        p for p in resultado.pontos_para_revisar if p.regra == "leitura_incerta"
    )
    assert ponto.tipo is TipoPonto.CONFIRMAR
    assert ponto.linha == 1
    assert ponto.campo == "classificacao"


def test_celula_ilegivel_no_cabecalho_tambem_pede_confirmacao(base):
    resultado = validar_folha(folha(matricula=Celula.ilegivel()), base)

    acionadas = regras_acionadas(resultado)
    assert "cab_completo" not in acionadas
    assert "leitura_incerta" in acionadas


def test_os_tres_estados_de_leitura_sao_distintos():
    assert Celula.lida("3").estado is EstadoLeitura.PREENCHIDA
    assert Celula.vazia().estado is EstadoLeitura.VAZIA
    assert Celula.ilegivel().estado is EstadoLeitura.ILEGIVEL


def test_celula_guarda_o_texto_cru_sem_converter_para_numero():
    # O motor precisa poder representar "PF" numa coluna numerica - e
    # exatamente isso que as regras de dominio existem para apontar.
    celula = Celula.lida("PF")

    assert celula.valor == "PF"
    assert isinstance(celula.valor, str)


def test_texto_so_com_espaco_conta_como_vazio_e_nao_como_preenchido():
    assert Celula.lida("   ").estado is EstadoLeitura.VAZIA


# --------------------------------------------------------------------------
# INDEPENDENCIA ENTRE REGRAS
# --------------------------------------------------------------------------

def test_um_campo_fora_do_dominio_nao_dispara_regra_de_outro_campo(base):
    resultado = validar_folha(folha([linha(1, local="7")]), base)

    assert regras_acionadas(resultado) == {"local_dominio"}


def test_varios_problemas_na_mesma_folha_sao_apontados_todos(base):
    resultado = validar_folha(
        folha([linha(1, local="7", quantidade="0", ocorrencia="SIM")]), base
    )

    assert regras_acionadas(resultado) == {
        "local_dominio", "quantidade_min", "sn_ocorrencia"
    }


def test_problema_na_linha_2_nao_e_reportado_na_linha_1(base):
    resultado = validar_folha(folha([linha(1), linha(2, quantidade="0")]), base)

    ponto = next(p for p in resultado.pontos_para_revisar if p.regra == "quantidade_min")
    assert ponto.linha == 2


# --------------------------------------------------------------------------
# ENTRE FOLHAS DO MESMO MAPEADO
# --------------------------------------------------------------------------

def _folha_de(horas: int, minutos: int, numero: str, nome="ANA SOUZA",
              matricula="T556714") -> Folha:
    return Folha(
        cabecalho=cab(numero_folha=numero, nome=nome, matricula=matricula),
        linhas=[linha(1, hora=str(horas), minutos=str(minutos), segundos="0")],
    )


def test_soma_8h_aceita_exatamente_8_horas(base):
    resultado = validar_conjunto(
        Conjunto(folhas=[_folha_de(4, 0, "1"), _folha_de(4, 0, "2")]), base
    )

    assert "soma_8h" not in regras_acionadas(resultado)


def test_soma_8h_aceita_a_margem_de_15_minutos(base):
    for h, m in ((7, 45), (8, 15)):
        resultado = validar_conjunto(Conjunto(folhas=[_folha_de(h, m, "1")]), base)
        assert "soma_8h" not in regras_acionadas(resultado)


def test_soma_8h_acusa_tempo_total_abaixo_da_margem(base):
    # Manual, p. 37 e p. 56: o total cronometrado deve fechar 8 horas,
    # com margem de 15 minutos para mais ou para menos.
    resultado = validar_conjunto(Conjunto(folhas=[_folha_de(6, 0, "1")]), base)

    assert "soma_8h" in regras_acionadas(resultado)


def test_soma_8h_acusa_tempo_total_acima_da_margem(base):
    resultado = validar_conjunto(Conjunto(folhas=[_folha_de(9, 0, "1")]), base)

    assert "soma_8h" in regras_acionadas(resultado)


def test_soma_por_mapeado_aceita_conjunto_de_um_unico_mapeado(base):
    resultado = validar_conjunto(
        Conjunto(folhas=[_folha_de(4, 0, "1"), _folha_de(4, 0, "2")]), base
    )

    assert "soma_por_mapeado" not in regras_acionadas(resultado)


def test_soma_por_mapeado_acusa_folhas_de_mapeados_diferentes_no_mesmo_grupo(base):
    # Manual, p. 37 e Guia, secao 1.5: trocou de mapeado, troca de folha -
    # e o agrupamento e por mapeado, nao por consultor.
    resultado = validar_conjunto(
        Conjunto(folhas=[
            _folha_de(4, 0, "1"),
            _folha_de(4, 0, "2", nome="JOAO LIMA", matricula="T999999"),
        ]),
        base,
    )

    assert "soma_por_mapeado" in regras_acionadas(resultado)


def test_soma_8h_nao_e_avaliada_quando_o_agrupamento_esta_errado(base):
    # Somar tempo de mapeados diferentes produziria um numero sem sentido.
    resultado = validar_conjunto(
        Conjunto(folhas=[
            _folha_de(1, 0, "1"),
            _folha_de(1, 0, "2", nome="JOAO LIMA", matricula="T999999"),
        ]),
        base,
    )

    assert "soma_8h" not in regras_acionadas(resultado)


def test_soma_8h_nao_e_avaliada_com_tempo_ilegivel(base):
    ilegivel = Folha(
        cabecalho=cab(),
        linhas=[linha(1, hora=Celula.ilegivel())],
    )
    resultado = validar_conjunto(Conjunto(folhas=[ilegivel]), base)

    assert "soma_8h" not in regras_acionadas(resultado)
    assert "leitura_incerta" in regras_acionadas(resultado)


def test_validar_conjunto_tambem_roda_as_regras_de_cada_folha(base):
    resultado = validar_conjunto(
        Conjunto(folhas=[_folha_de(4, 0, "1"),
                         Folha(cabecalho=cab(numero_folha="2"),
                               linhas=[linha(1, hora="4", minutos="0",
                                             segundos="0", local="7")])]),
        base,
    )

    assert "local_dominio" in regras_acionadas(resultado)


# --------------------------------------------------------------------------
# Categorias de erro documentadas no Manual (p. 42 e 43)
#
# O Manual traz uma folha correta (p. 42) e uma incorreta (p. 43), mas
# so como FOTO - os valores nao existem de forma estruturada no projeto.
# Nada foi transcrito da imagem aqui. Os casos abaixo reproduzem as
# CATEGORIAS de defeito que o texto do slide 43 lista, com valores
# montados neste arquivo.
# --------------------------------------------------------------------------

def test_categoria_do_manual_formato_diferente_do_esperado(base):
    # Slide 43: "Formatos de dados diferentes do esperado nao serao aceitos."
    resultado = validar_folha(folha([linha(1, clientes="PF", venda_concluida="SIM")]), base)

    assert {"clientes_dominio", "sn_venda"} <= regras_acionadas(resultado)


def test_categoria_do_manual_valores_em_branco(base):
    # Slide 43: "Nao deixe valores em branco. Sempre preencha todos os campos."
    resultado = validar_folha(folha([linha(1, produto=Celula.vazia(),
                                           segmento=Celula.vazia())]), base)

    campos = {p.campo for p in resultado.pontos_para_revisar
              if p.regra == "linha_sem_brancos"}
    assert campos == {"produto", "segmento"}


# --------------------------------------------------------------------------
# Decisao de produto (20/09/2026): a coluna "Ocorrencia" esta fora do
# escopo funcional do software -- nao gera feedback ao consultor.
#
# O isolamento acontece no LIMITE DO RELATORIO, nao no motor: a celula
# continua sendo lida e continua entrando em `linha_sem_brancos`, senao
# toda linha preenchida ganharia um branco falso. Estes testes fixam esse
# contrato.
# --------------------------------------------------------------------------

def test_ocorrencia_continua_sendo_cobrada_pelo_motor(base):
    # O motor NAO muda: quem filtra e a camada de analise.
    resultado = validar_folha(folha([linha(1, ocorrencia=Celula.vazia())]), base)

    campos = {p.campo for p in resultado.pontos_para_revisar
              if p.regra == "linha_sem_brancos"}
    assert campos == {"ocorrencia"}


def test_todo_ponto_de_ocorrencia_e_reconhecido_como_fora_do_escopo(base):
    # Um filtro por campo cobre as duas regras que tocam a coluna
    # (`sn_ocorrencia` e `linha_sem_brancos`) -- por isso nenhuma regra
    # precisou ser desligada.
    vazia = validar_folha(folha([linha(1, ocorrencia=Celula.vazia())]), base)
    invalida = validar_folha(folha([linha(1, ocorrencia=Celula.lida("X"))]), base)

    pontos = vazia.pontos_para_revisar + invalida.pontos_para_revisar
    de_ocorrencia = [p for p in pontos if p.campo == "ocorrencia"]

    assert {p.regra for p in de_ocorrencia} == {"linha_sem_brancos", "sn_ocorrencia"}
    assert all(regras.fora_do_escopo_funcional(p) for p in de_ocorrencia)


def test_filtro_nao_remove_ponto_de_outra_coluna(base):
    resultado = validar_folha(folha([linha(1, clientes="PF")]), base)

    sobrando = [p for p in resultado.pontos_para_revisar
                if not regras.fora_do_escopo_funcional(p)]
    assert any(p.regra == "clientes_dominio" for p in sobrando)


def test_a_coluna_nao_foi_removida_do_modelo():
    # Remove-la faria `linha_sem_brancos` acusar um branco inexistente em
    # cada linha em uso de cada ficha.
    assert "ocorrencia" in Linha.CAMPOS
    assert regras.CAMPOS_FORA_DO_ESCOPO == ("ocorrencia",)


# ==========================================================================
# CAMPO VAZIO NUNCA VIRA VALOR PADRAO
#
# Confirmacao da regra de produto: nenhum campo da folha pode ficar em
# branco, e branco NAO pode ser lido como 0, como "N", nem como qualquer
# outro padrao. Se o valor certo e zero, o consultor tem de ter escrito
# "0" na folha.
#
# Estes testes nao acrescentam comportamento novo: eles fixam o que
# `linha_sem_brancos` e as regras de dominio/faixa ja fazem, para que
# ninguem "simplifique" isso mais tarde tratando vazio como zero.
# ==========================================================================

CAMPOS_OBRIGATORIOS = (
    "segmento", "agenda_certo", "classificacao", "local", "atendimento",
    "clientes", "venda_concluida", "hora", "minutos", "segundos",
    "quantidade", "produto", "detalhamento", "num_processo",
)


@pytest.mark.parametrize("campo", CAMPOS_OBRIGATORIOS)
def test_campo_vazio_em_linha_usada_vira_erro(base, campo):
    resultado = validar_folha(folha([linha(1, **{campo: Celula.vazia()})]), base)

    brancos = [p for p in resultado.pontos_para_revisar
               if p.regra == "linha_sem_brancos" and p.campo == campo]

    assert len(brancos) == 1
    assert brancos[0].tipo is TipoPonto.ERRO
    assert brancos[0].linha == 1


def test_hora_vazia_nao_e_tratada_como_zero(base):
    """O caso do bloco de tempo. Hora em branco e erro de preenchimento;
    se a atividade durou menos de uma hora, o consultor escreve "0"."""
    vazia = folha([linha(1, hora=Celula.vazia())])

    resultado = validar_folha(vazia, base)
    acionadas = regras_acionadas(resultado)

    assert "linha_sem_brancos" in acionadas
    # Nao pode passar pela regra de faixa como se valesse 0.
    assert "tempo_minutos" not in acionadas
    # E a soma do dia se abstem, em vez de somar um numero incompleto.
    assert not regras.soma_8h(Conjunto(folhas=[vazia]), base)


def test_hora_zero_escrita_e_preenchimento_valido(base):
    """`0` escrito na folha e campo preenchido, nao branco."""
    resultado = validar_folha(folha([linha(1, hora="0")]), base)

    brancos = [p for p in resultado.pontos_para_revisar
               if p.regra == "linha_sem_brancos" and p.campo == "hora"]

    assert brancos == []


@pytest.mark.parametrize("campo,regra_sn", [
    ("agenda_certo", "sn_agenda"),
    ("venda_concluida", "sn_venda"),
])
def test_campo_sn_vazio_nao_vira_n(base, campo, regra_sn):
    """Coluna de dominio fechado em branco vira alerta de branco -- nunca
    e convertida para uma das duas opcoes."""
    resultado = validar_folha(folha([linha(1, **{campo: Celula.vazia()})]), base)

    pontos = [p for p in resultado.pontos_para_revisar if p.campo == campo]

    assert {p.regra for p in pontos} == {"linha_sem_brancos"}
    # A regra de dominio S/N nao opina sobre celula vazia: ela nao tem
    # valor para julgar, e inventar um esconderia o branco.
    assert regra_sn not in regras_acionadas(resultado)


def test_a_leitura_vazia_e_preservada_como_vazia(base):
    """O estado chega ao relatorio como VAZIA -- nao como PREENCHIDA com
    um valor assumido."""
    f = folha([linha(1, hora=Celula.vazia())])

    assert f.linhas[0].hora.estado is EstadoLeitura.VAZIA
    assert f.linhas[0].hora.valor is None
