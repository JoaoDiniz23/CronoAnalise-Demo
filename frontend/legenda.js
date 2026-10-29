/**
 * Códigos da folha física para os campos da base de atividades.
 *
 * O cartão do chat mostra o que o consultor escreve na folha (ex.:
 * "19 – TNP: Gestão de Equipe"), não só o texto da base. Os códigos e
 * descrições vêm de `dados/legenda_folha_fisica.yaml` (nesta demo, legenda
 * fictícia). A correspondência
 * base → código é por nome, porque a base não traz o código;
 * `tests/legenda.test.js` garante que todo valor da base tem código.
 *
 * Valor sem correspondência volta como está — nunca some da tela.
 */

// Chave: texto da base normalizado (sem acento, minúsculo, espaços simples).
const CLASSIFICACAO = {
  "venda": [1, "C: Venda"],
  "formalizacao": [2, "C: Formalização"],
  "pos venda": [3, "C: Pós Venda"],
  "gestao da carteira de cliente": [4, "C: Gestão da Carteira de Clientes"],
  "visita": [5, "C: Visita"],
  "suporte interno": [6, "C: Suporte Interno"],
  "treinamento": [8, "C: Treinamento"],
  "transferencias entre contas, pagamento de fatura e/ou parcela": [
    9,
    "O: Transferências entre contas, pagamento de fatura e/ou parcela",
  ],
  "deposito": [10, "O: Depósito"],
  "saque": [11, "O: Saque"],
  "recebimento de titulos": [12, "O: Recebimento de Título"],
  "pendencia regulatoria": [13, "O: Pendência regulatória"],
  "numerario": [14, "O: Numerário"],
  "manutencao/gestao da loja ou gestao de fila": [15, "O: Manutenção/Gestão de Loja ou Gestão de Fila"],
  "tratamento de cheque": [16, "O: Tratamento de Cheques"],
  // A base traz o parêntese sem fechar: "(malote/estoque/cartão".
  "gestao de tangiveis (malote/estoque/cartao": [17, "O: Gestão de Tangíveis (malotes/estoque/cartão)"],
  "tempo nao produtivo": [18, "TNP: Tempo Não Produtivo"],
  "gestao de equipe": [19, "TNP: Gestão de Equipe"],
  "tnp do consultor": [20, "TNP: TNP do Consultor"],
};

const CLIENTES = {
  "pessoa fisica": [1, "Cliente PF"],
  "pessoa juridica": [2, "Cliente PJ"],
  "nao cliente do banco": [3, "Não cliente do Banco"],
  "nao identificado": [4, "Não identificado"],
  "nao foi um atendimento ao cliente": [5, "Não atendimento ao cliente"],
};

const SEGMENTO = {
  "varejo": ["V", "Varejo"],
  "alta renda": ["AR", "Alta Renda"],
  "private": ["PV", "Private"],
  "mei": ["MEI", "MEI"],
  "pequena empresa": ["PE", "Pequena Empresa"],
  "agro pf": ["APF", "Agro PF"],
  "agro pj": ["APJ", "Agro PJ"],
  "segmento nao identificado": ["SNI", "Segmento não Identificado"],
  "nao identificado": ["SNI", "Segmento não Identificado"],
  "nao atendimento ao cliente": ["Não", "Não atendimento ao cliente"],
  "nao cliente do banco": ["NCB", "Não cliente do Banco"],
};

const ATENDIMENTO = {
  "e-mail": [1, "E-mail"],
  "ligacao de voz": [2, "Ligação de Voz"],
  "nao foi um atendimento ao cliente": [3, "Não foi um atendimento ao cliente"],
  "outros": [4, "Outro"],
  "presencial": [5, "Presencial"],
  "chat": [6, "Chat"],
};

export function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

function rotular(tabela, valor) {
  const achado = tabela[normalizar(valor)];
  if (!achado) return null;
  const [codigo, descricao] = achado;
  return codigo === descricao ? String(codigo) : `${codigo} – ${descricao}`;
}

function rotularLista(tabela, lista) {
  return lista.map((valor) => rotular(tabela, valor) ?? valor).join(", ");
}

/**
 * Produto como vai escrito na folha: sem o parêntese explicativo
 * ("Capital de Giro (Empréstimo)" → "Capital de Giro"). Guia de
 * atualização §1.3 — "os nomes dos produtos perderam os parênteses" — e
 * regra R14 do agente revisor. A base ainda traz os parênteses;
 * a busca continua usando o nome completo (o parêntese ajuda a achar).
 */
export function produtoDaFolha(produto) {
  return String(produto ?? "").replace(/\s*\([^)]*\)\s*$/, "").trim() || String(produto ?? "");
}

/** "Gestão de equipe + TNP" → "19 – TNP: Gestão de Equipe" (null se desconhecido). */
export function classificacaoDaFolha(subgrupo) {
  const grupo = String(subgrupo ?? "").split(" + ")[0];
  return rotular(CLASSIFICACAO, grupo);
}

/** Tempo parado do próprio consultor (Guia §1.4): código 20, fora da base. */
export const CLASSIFICACAO_TNP_CONSULTOR = "20 – TNP: TNP do Consultor";

export const clientesDaFolha = (lista) => rotularLista(CLIENTES, lista);
export const segmentoDaFolha = (lista) => rotularLista(SEGMENTO, lista);
export const atendimentoDaFolha = (lista) => rotularLista(ATENDIMENTO, lista);

/** Valores da base que não têm código — usado só pelo teste de cobertura. */
export function valoresSemCodigo(atividade) {
  const faltando = [];
  if (!classificacaoDaFolha(atividade.subgrupo)) faltando.push(`subgrupo: ${atividade.subgrupo}`);
  const listas = [
    ["clientes", CLIENTES],
    ["segmento", SEGMENTO],
    ["atendimento", ATENDIMENTO],
  ];
  for (const [campo, tabela] of listas) {
    for (const valor of String(atividade[campo]).split(",")) {
      if (valor.trim() && !rotular(tabela, valor)) faltando.push(`${campo}: ${valor.trim()}`);
    }
  }
  return faltando;
}
