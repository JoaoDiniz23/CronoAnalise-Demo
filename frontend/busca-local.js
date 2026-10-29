/**
 * Busca determinística NO CELULAR — funciona sem internet.
 *
 * Cópia fiel, em JavaScript, da parte sem LLM do backend:
 * `backend/busca/texto.py` (normalização/stemming), `recuperador.py`
 * (busca por palavras) e `servico.py` (`correspondencia_exata`,
 * `correspondencia_por_nome`). Requisito do usuário (23/09/2026): o
 * chatbot PRECISA funcionar offline; só a interpretação por LLM depende
 * de rede.
 *
 * As duas cópias não podem divergir: `tests/busca-local.test.js` compara
 * esta com `tests/dados_busca/paridade_busca.json`, gerado do Python por
 * `scripts/gerar_paridade_busca.py` (e `test_paridade_busca.py` falha se o
 * Python mudar sem regenerar). Mexeu em um lado, mexa no outro.
 *
 * Módulo puro: sem DOM, sem fetch. Devolve objetos no mesmo formato do
 * `ResultadoBusca` da API, para a tela desenhar igual.
 */

// ------------------------------- texto.py --------------------------------

const SUFIXOS = [
  "acoes", "acao", "amento", "imento", "mente", "ando", "endo", "indo",
  "aria", "eria", "iria", "adora", "adoras", "adores", "ador", "ante",
  "adas", "ados", "idas", "idos", "ada", "ado", "ida", "ido",
  "coes", "cao", "ar", "er", "ir",
  "aram", "eram", "iram", "avam", "ava", "ou", "eu", "iu",
  "encia", "ancia",
].sort((a, b) => b.length - a.length); // estável: empate mantém a ordem, como o sorted() do Python

const STOPWORDS = new Set([
  "estou", "fazendo", "fazer", "faco", "quero", "queria", "preciso",
  "gostaria", "sobre", "como", "qual", "quais", "um", "uma", "uns",
  "umas", "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as",
  "para", "pra", "por", "no", "na", "nos", "nas", "em", "com", "que",
  "meu", "minha", "ao", "aos", "sou", "esse", "essa", "este", "esta",
  "isso", "ele", "ela", "eu", "se", "ja", "la", "aqui", "tem", "ter",
  "me", "ver",
  "consultor", "consultora", "gerente", "funcionario", "funcionaria",
  "estava", "esteve", "foi", "era", "seu", "sua", "seus", "suas",
  "dele", "dela", "lhe", "pelo", "pela", "pelos", "pelas", "num",
  "numa", "muito", "pouco", "mais", "menos", "tambem", "entao",
  "depois", "antes", "durante", "quando", "onde", "ali", "algum",
  "alguma", "outro", "outra", "ou",
  // verbos de relato — ver texto.py
  "fala", "falar", "falando", "falou", "conversa", "conversar",
  "conversando", "conversou", "comentar", "comentando", "comentou",
  "dizer", "dizendo", "disse",
  // tempo: hora e circunstância não são a atividade — ver texto.py
  "inicio", "fim", "dia", "dias", "manha", "tarde", "noite", "jornada",
  "expediente", "hoje", "ontem", "cedo",
]);

const EQUIVALENTES = {
  segunda: "2", "2a": "2", "2o": "2",
  saca: "saque", sacar: "saque", sacou: "saque", sacando: "saque",
  sacaram: "saque", sacado: "saque",
  // "abrir" não casa com "abertura"; a agência é a "loja" — ver texto.py
  ...Object.fromEntries(
    ["abrir", "abre", "abrem", "abriu", "abriram", "abrindo", "abria", "abriam",
      "aberto", "aberta", "abertos", "abertas"].map((p) => [p, "abertura"]),
  ),
  agencia: "loja", agencias: "loja",
};

export function normalizar(texto) {
  return String(texto ?? "").toLowerCase().normalize("NFD").replace(/\p{Mn}/gu, "");
}

export function radical(palavra) {
  const s = palavra.endsWith("s") ? palavra.slice(0, -1) : palavra;
  for (const sufixo of SUFIXOS) {
    if (s.endsWith(sufixo) && s.length - sufixo.length >= 3) {
      return s.slice(0, -sufixo.length);
    }
  }
  return s;
}

export function palavras(texto) {
  return normalizar(texto)
    .split(/[^a-z0-9]+/)
    .filter(Boolean)
    .map((p) => EQUIVALENTES[p] ?? p);
}

export function radicais(texto) {
  const vistos = new Set();
  for (const p of palavras(texto)) {
    if ((p.length < 2 && !/^\d+$/.test(p)) || STOPWORDS.has(p)) continue;
    vistos.add(radical(p));
  }
  return [...vistos];
}

// -------------------- texto.py: correção de digitação --------------------

/** Damerau-Levenshtein restrita; devolve limite + 1 ao passar do limite. */
export function distanciaEdicao(a, b, limite) {
  if (Math.abs(a.length - b.length) > limite) return limite + 1;
  let anterior2 = [];
  let anterior = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const atual = [i, ...new Array(b.length).fill(0)];
    for (let j = 1; j <= b.length; j++) {
      const custo = a[i - 1] === b[j - 1] ? 0 : 1;
      atual[j] = Math.min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + custo);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        atual[j] = Math.min(atual[j], anterior2[j - 2] + 1);
      }
    }
    if (Math.min(...atual) > limite) return limite + 1;
    anterior2 = anterior;
    anterior = atual;
  }
  return anterior[b.length];
}

function criarCorretor(textosDaBase) {
  const vocabulario = new Set(textosDaBase.flatMap((t) => palavras(t)));
  const raizes = [...new Set([...vocabulario].map(radical))];
  function corrigirPalavra(p) {
    if (vocabulario.has(p) || p.length <= 4 || STOPWORDS.has(p) || /^\d+$/.test(p)) return p;
    const rp = radical(p);
    if (rp.length >= 4 && raizes.some((r) => r.startsWith(rp))) return p;
    const limite = 1;
    let melhor = limite + 1;
    let empatadas = [];
    for (const v of vocabulario) {
      const d = distanciaEdicao(p, v, limite);
      if (d < melhor) {
        melhor = d;
        empatadas = [v];
      } else if (d === melhor && d <= limite) {
        empatadas.push(v);
      }
    }
    return melhor <= limite && empatadas.length === 1 ? empatadas[0] : p;
  }
  return (texto) => palavras(texto).map(corrigirPalavra).join(" ");
}

// ----------------------------- recuperador.py ----------------------------

const PESOS_CAMPOS = { atividade: 2.0, produto: 2.0, subgrupo: 1.0 };
const MIN_PREFIXO = 4;

function radicaisCasam(consulta, documento) {
  if (consulta === documento) return true;
  const menor = Math.min(consulta.length, documento.length);
  return menor >= MIN_PREFIXO && (documento.startsWith(consulta) || consulta.startsWith(documento));
}

// round(x, 4) do Python arredonda "meio para par"; nas pontuações reais
// (somas de logaritmos) o empate exato em .5 não acontece.
const arredondar4 = (x) => Math.round(x * 1e4) / 1e4;

// ------------------------------- servico.py ------------------------------

const MAX_OPCOES_DIRETAS = 12;
const MENSAGEM_ALMOCO =
  'almoço do colaborador: Tempo não produtivo, com "Almoço" no Detalhamento; almoço seu (consultor): Almoço';
const LIMITE_CANDIDATOS = 10;

function contem(maior, menor) {
  for (const x of menor) if (!maior.has(x)) return false;
  return true;
}

function iguais(a, b) {
  return a.size === b.size && contem(a, b);
}

function posicoes(texto, trecho) {
  const n = trecho.length;
  if (n === 0) return [];
  const achados = [];
  for (let i = 0; i + n <= texto.length; i++) {
    if (trecho.every((p, j) => texto[i + j] === p)) achados.push(i);
  }
  return achados.map((inicio) => new Set(Array.from({ length: n }, (_, j) => inicio + j)));
}

function citaOsDoisNomes(ditas, atividade) {
  const trechosAtividade = posicoes(ditas, palavras(atividade.atividade));
  const trechosProduto = posicoes(ditas, palavras(atividade.produto));
  return trechosAtividade.some((a) => trechosProduto.some((p) => ![...a].some((i) => p.has(i))));
}

/**
 * Índice da base, montado uma vez (~800 registros). `atividades` é a lista
 * como vem de `GET /api/atividades`, na ordem da base oficial.
 */
export function criarBuscaLocal(atividades) {
  const indice = atividades.map((a) => ({
    atividade: a,
    radicaisPorCampo: Object.fromEntries(
      Object.keys(PESOS_CAMPOS).map((campo) => [campo, new Set(radicais(a[campo]))]),
    ),
    nomeAtividade: new Set(radicais(a.atividade)),
    nomeProduto: new Set(radicais(a.produto)),
    atividadeEProduto: new Set(radicais(`${a.atividade} ${a.produto}`)),
  }));
  const corrigir = criarCorretor(atividades.flatMap((a) => [a.atividade, a.produto, a.subgrupo]));
  const vocabulario = new Set();
  for (const item of indice) {
    for (const rs of Object.values(item.radicaisPorCampo)) for (const r of rs) vocabulario.add(r);
  }

  function pesoNoRegistro(r, item) {
    let peso = 0;
    for (const [campo, rs] of Object.entries(item.radicaisPorCampo)) {
      for (const d of rs) {
        if (radicaisCasam(r, d)) {
          peso = Math.max(peso, PESOS_CAMPOS[campo]);
          break;
        }
      }
    }
    return peso;
  }

  function correspondenciaExata(texto) {
    const ditas = palavras(texto);
    const ditos = new Set(radicais(texto));
    const achadas = indice
      .filter((item) => contem(item.atividadeEProduto, ditos) && citaOsDoisNomes(ditas, item.atividade))
      .map((item) => item.atividade);
    return achadas.length === 1 ? achadas[0] : null;
  }

  function correspondenciaPorNome(texto) {
    const ditos = new Set(radicais(texto));
    if (ditos.size === 0) return [];
    const achadas = indice
      .filter((item) => iguais(ditos, item.nomeAtividade) || iguais(ditos, item.nomeProduto))
      .map((item) => item.atividade);
    // "almoço" sozinho: colaborador (Tempo não produtivo) e consultor (Almoço) — ver servico.py.
    if (achadas.length === 1 && eAlmoco(achadas[0])) return [...tempoNaoProdutivo(), ...achadas];
    return achadas;
  }

  function eAlmoco(atividade) {
    return iguais(new Set(radicais("Almoço")), new Set(radicais(atividade.atividade)));
  }

  function tempoNaoProdutivo() {
    const alvo = new Set(radicais("Tempo não produtivo"));
    return indice.filter((item) => iguais(alvo, item.nomeAtividade)).map((item) => item.atividade);
  }

  function nomeDeProduto(texto) {
    const ditos = new Set(radicais(texto));
    return ditos.size > 0 && indice.some((item) => iguais(ditos, item.nomeProduto));
  }

  function buscarCandidatos(texto, limite = LIMITE_CANDIDATOS) {
    const consulta = radicais(texto).filter((r) => {
      for (const v of vocabulario) if (radicaisCasam(r, v)) return true;
      return false;
    });
    if (consulta.length === 0) return [];
    const total = indice.length;
    const pesos = new Map(consulta.map((r) => [r, indice.map((item) => pesoNoRegistro(r, item))]));
    const idf = new Map();
    for (const [r, lista] of pesos) {
      const df = lista.filter((p) => p > 0).length;
      idf.set(r, Math.log(1 + (total - df + 0.5) / (df + 0.5)));
    }
    const palavraDe = new Map();
    for (const p of palavras(texto)) {
      const rp = radicais(p);
      for (const r of consulta) {
        if (!palavraDe.has(r) && rp.length && radicaisCasam(r, rp[0])) palavraDe.set(r, p);
      }
    }
    const pontuados = [];
    indice.forEach((item, i) => {
      const casados = consulta.filter((r) => pesos.get(r)[i] > 0);
      if (casados.length === 0) return;
      const pontuacao = casados.reduce((soma, r) => soma + idf.get(r) * pesos.get(r)[i], 0);
      pontuados.push({
        atividade: item.atividade,
        pontuacao: arredondar4(pontuacao),
        termos_casados: casados.map((r) => palavraDe.get(r) ?? r),
      });
    });
    pontuados.sort((a, b) => b.pontuacao - a.pontuacao || a.atividade.id - b.atividade.id);
    return pontuados.slice(0, limite);
  }

  /**
   * Resolve sem rede quando dá (nome exato). Devolve um `ResultadoBusca`
   * ou `null` quando a decisão precisa do LLM.
   */
  function resolverSemLLM(texto) {
    texto = String(texto ?? "").trim();
    if (radicais(texto).length === 0) return null; // o backend explica o motivo
    // Mesma correção de digitação do backend (servico.py), com a mesma nota.
    const busca = corrigir(texto);
    const nota = busca !== palavras(texto).join(" ") ? ` (entendido como "${busca}")` : "";
    const base = { texto_original: texto, origem: "busca", atividade: null, alternativas: [], candidatos: [] };
    const exata = correspondenciaExata(busca);
    if (exata) {
      return { ...base, status: "encontrada", atividade: exata,
        justificativa: "nome da atividade e do produto informados exatamente" + nota };
    }
    const porNome = correspondenciaPorNome(busca);
    if (porNome.length === 1) {
      return { ...base, status: "encontrada", atividade: porNome[0],
        justificativa: "nome oficial informado exatamente" + nota };
    }
    // Nome de produto: lista inteira, sem limite (ver MAX_OPCOES_DIRETAS no servico.py).
    if (porNome.length >= 2 && (porNome.length <= MAX_OPCOES_DIRETAS || nomeDeProduto(busca))) {
      const almoco = porNome.length === 2 && porNome.some(eAlmoco);
      return { ...base, status: "ambigua", alternativas: porNome,
        justificativa: (almoco ? MENSAGEM_ALMOCO : "há mais de uma atividade com esse nome; escolha a que foi feita") + nota };
    }
    return null;
  }

  /**
   * Servidor não respondeu e não há nome exato: as mais parecidas pela
   * busca por palavras. `motivo` (sem_internet, sessao_expirada,
   * limite_diario, servidor_indisponivel) define o aviso na tela.
   */
  function resultadoOffline(texto, motivo = "sem_internet") {
    texto = String(texto ?? "").trim();
    const candidatos = buscarCandidatos(corrigir(texto));
    return {
      texto_original: texto,
      status: "llm_indisponivel",
      origem: "busca",
      atividade: null,
      alternativas: [],
      candidatos,
      erro: { tipo: motivo, mensagem: "" },
    };
  }

  return {
    corrigir, correspondenciaExata, correspondenciaPorNome, nomeDeProduto,
    buscarCandidatos, resolverSemLLM, resultadoOffline,
  };
}
