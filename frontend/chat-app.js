/**
 * Tela de chat (chatbot de busca de atividades).
 *
 * Reaproveita 100% do núcleo puro em `busca.js` (Fase 1C) — só muda a
 * apresentação: histórico de bolhas de conversa em vez de um painel único
 * substituído a cada busca. Módulo independente do cronômetro (não importa
 * nem é importado por `app.js`/`cronometro.js`), mesmo espírito de
 * `busca-app.js` original (ver CLAUDE.md — "três módulos, sem dependência
 * entre eles").
 *
 * Toda a montagem da tela usa `textContent`/`createElement`, nunca
 * `innerHTML`: `justificativa` é texto livre do LLM, não deve virar HTML
 * interpretado.
 */

import {
  avisoDeCota,
  diaLocal,
  interpretarResultado,
  lapEmAndamento,
  textoMomento,
  montarPedidoBusca,
  podarConversa,
  tempoMaxServidorMs,
} from "./busca.js?v=20260929c";
import { criarBuscaLocal } from "./busca-local.js?v=20260929c";
import {
  CLASSIFICACAO_TNP_CONSULTOR,
  atendimentoDaFolha,
  classificacaoDaFolha,
  produtoDaFolha,
  clientesDaFolha,
  segmentoDaFolha,
} from "./legenda.js?v=20260929c";

const ROTA_BUSCA = "/api/atividades/buscar";
const ROTA_BASE = "/api/atividades";
// Rota pública e sem LLM: só acorda o servidor antes da 1ª busca.
const ROTA_AQUECER = "/health";
// Listas maiores que isso viram linhas compactas (toque abre os detalhes).
const LIMITE_LISTA_ABERTA = 12;
// Cópia da base no celular, para buscar sem internet (busca-local.js).
const CHAVE_BASE = "cronoanalise-atividades-v1";
// Conversa do dia: sobrevive se o iOS recarregar a aba; some ao fechar o app.
const CHAVE_CONVERSA = "cronoanalise-conversa-v1";
// Estado do cronômetro gravado por app.js: lido só para saber a lap atual.
const CHAVE_CRONOMETRO = "cronoanalise:cronometro:v1";

const MENSAGEM_ERRO_REDE =
  "Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.";

/* --------------------------- base no celular ----------------------------- */

let buscaLocal = null;

function usarBase(atividades) {
  if (Array.isArray(atividades) && atividades.length > 0) {
    buscaLocal = criarBuscaLocal(atividades);
    return true;
  }
  return false;
}

// 1º a cópia guardada (abre e busca mesmo sem sinal); depois tenta
// atualizar pela rede, em segundo plano, sem travar a tela.
try {
  usarBase(JSON.parse(localStorage.getItem(CHAVE_BASE) ?? "null"));
} catch {
  // cópia ilegível: segue sem ela até a rede responder
}

fetch(ROTA_BASE)
  .then((resposta) => (resposta.ok ? resposta.json() : null))
  .then((atividades) => {
    if (!usarBase(atividades)) return;
    try {
      localStorage.setItem(CHAVE_BASE, JSON.stringify(atividades));
    } catch {
      // sem espaço/permissão: a busca local vale até fechar o app
    }
  })
  .catch(() => {
    // sem rede: fica a cópia guardada
  });

// Voltar ao app depois de um tempo em segundo plano: acorda o servidor de
// novo (sem gastar LLM) e apaga a conversa se o dia virou.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  aquecerServidor();
  if (conversa.length && conversa[0].dia !== diaLocal(Date.now())) {
    conversa = [];
    salvarConversa();
    el.historico.replaceChildren();
  }
});

function aquecerServidor() {
  fetch(ROTA_AQUECER, { method: "HEAD", cache: "no-store" }).catch(() => {});
}

const el = {
  form: document.getElementById("form-chat"),
  texto: document.getElementById("chat-texto"),
  botao: document.getElementById("btn-chat-enviar"),
  historico: document.getElementById("chat-historico"),
};

// Enquanto a pessoa digita a 1ª busca, o servidor já vai acordando.
el.texto.addEventListener("focus", aquecerServidor, { once: true });

el.form.addEventListener("submit", (evento) => {
  evento.preventDefault();
  const texto = el.texto.value.trim();
  if (!texto || el.botao.disabled) return;
  enviar(texto);
});

/* ------------------------------- conversa -------------------------------- */

// Cada busca vira { dia, texto, resposta } — dados, não HTML — e é
// redesenhada pelas mesmas funções ao reabrir.
let conversa = [];
try {
  conversa = podarConversa(JSON.parse(sessionStorage.getItem(CHAVE_CONVERSA) ?? "null"), diaLocal(Date.now()));
} catch {
  // conversa ilegível: começa vazia
}
for (const entrada of conversa) desenharEntrada(entrada);
rolarParaFinal();

function salvarConversa() {
  try {
    sessionStorage.setItem(CHAVE_CONVERSA, JSON.stringify(conversa));
  } catch {
    // sem espaço/permissão: a conversa vale até fechar o app
  }
}

function registrar(texto, resposta, momento) {
  const entrada = { dia: diaLocal(Date.now()), texto, resposta, momento };
  desenharResposta(texto, resposta, momento);
  conversa = podarConversa([...conversa, entrada], entrada.dia);
  salvarConversa();
  // Passou do limite: some da tela a busca mais antiga (pergunta + resposta).
  while (el.historico.querySelectorAll(".chat-bolha-usuario").length > conversa.length) {
    const primeira = el.historico.querySelector(".chat-bolha-usuario");
    while (primeira.nextElementSibling && !primeira.nextElementSibling.classList.contains("chat-bolha-usuario")) {
      primeira.nextElementSibling.remove();
    }
    primeira.remove();
  }
}

function desenharEntrada(entrada) {
  adicionarBolhaUsuario(entrada.texto);
  desenharResposta(entrada.texto, entrada.resposta, entrada.momento);
}

function desenharResposta(texto, resposta, momento) {
  let conteudo;
  if (resposta.tipo === "sem_servidor") {
    conteudo = conteudoSemServidor(texto, resposta.motivo);
  } else {
    conteudo = montarResposta(interpretarResultado(resposta.resultado));
    const aviso = avisoDeCota(resposta.resultado);
    if (aviso) conteudo.append(criarParagrafo(aviso.ultimo ? "busca-aviso-cota" : "busca-cota", aviso.texto));
  }
  const rodape = textoMomento(momento);
  if (rodape) conteudo.append(criarParagrafo("chat-momento", rodape));
  adicionarBolhaAssistente(conteudo);
}

// Lap e hora do ENVIO da pergunta (não da chegada da resposta).
function momentoAgora() {
  let bruto = null;
  try {
    bruto = JSON.parse(localStorage.getItem(CHAVE_CRONOMETRO) ?? "null");
  } catch {
    // cronômetro ilegível: fica só a hora
  }
  return { lap: lapEmAndamento(bruto), emMs: Date.now() };
}

/* -------------------------------- busca ---------------------------------- */

let ultimaBuscaServidorMs = null;

async function enviar(texto) {
  const momento = momentoAgora();
  adicionarBolhaUsuario(texto);
  el.texto.value = "";

  // Nome exato resolve no próprio celular: na hora, com ou sem internet.
  const local = buscaLocal?.resolverSemLLM(texto);
  if (local) {
    registrar(texto, { tipo: "resultado", resultado: local }, momento);
    return;
  }

  // O celular já sabe que está sem rede: não espera o fetch falhar.
  if (navigator.onLine === false && buscaLocal) {
    registrar(texto, { tipo: "sem_servidor", motivo: "sem_internet" }, momento);
    return;
  }

  const bolhaEspera = adicionarBolhaEspera();
  definirCarregando(true);
  const cancelar = new AbortController();
  const relogio = setTimeout(() => cancelar.abort(), tempoMaxServidorMs(ultimaBuscaServidorMs, Date.now()));
  try {
    const resposta = await fetch(ROTA_BUSCA, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(montarPedidoBusca(texto)),
      signal: cancelar.signal,
    });
    ultimaBuscaServidorMs = Date.now();
    bolhaEspera.remove();
    if (!resposta.ok) {
      registrar(texto, { tipo: "sem_servidor", motivo: motivoDaFalha(resposta.status) }, momento);
      return;
    }
    registrar(texto, { tipo: "resultado", resultado: await resposta.json() }, momento);
  } catch {
    // Sem rede ou servidor fora do ar (a exceção varia por navegador).
    bolhaEspera.remove();
    registrar(texto, { tipo: "sem_servidor", motivo: "sem_internet" }, momento);
  } finally {
    clearTimeout(relogio);
    definirCarregando(false);
  }
}

// 401 = cookie vencido (precisa entrar de novo); 429 = teto diário
// (backend/acesso.py). "Sem internet" fica só para falha de rede de verdade.
function motivoDaFalha(status) {
  if (status === 401) return "sessao_expirada";
  if (status === 429) return "limite_diario";
  return "servidor_indisponivel";
}

// Sem servidor: as mais parecidas pela busca por palavras, no celular.
// Só cai na mensagem de erro se a base nunca chegou a ser baixada.
function conteudoSemServidor(texto, motivo) {
  const conteudo = document.createDocumentFragment();
  if (buscaLocal) {
    conteudo.append(montarResposta(interpretarResultado(buscaLocal.resultadoOffline(texto, motivo))));
  } else {
    conteudo.append(criarParagrafo("busca-erro", MENSAGEM_ERRO_REDE));
  }
  if (motivo === "sessao_expirada") {
    const link = document.createElement("a");
    link.href = "/login";
    link.className = "busca-link-login";
    link.textContent = "Entrar de novo";
    conteudo.prepend(link);
  }
  return conteudo;
}

function definirCarregando(carregando) {
  el.botao.disabled = carregando;
  el.botao.textContent = carregando ? "Enviando…" : "Enviar";
}

/* --------------------------------- bolhas -------------------------------- */

function adicionarBolhaUsuario(texto) {
  const bolha = document.createElement("div");
  bolha.className = "chat-bolha chat-bolha-usuario";
  bolha.textContent = texto;
  el.historico.append(bolha);
  rolarParaFinal();
}

function adicionarBolhaEspera() {
  const bolha = document.createElement("div");
  bolha.className = "chat-bolha chat-bolha-assistente chat-bolha-espera";
  bolha.textContent = "Buscando…";
  el.historico.append(bolha);
  rolarParaFinal();
  return bolha;
}

function adicionarBolhaAssistente(conteudo) {
  const bolha = document.createElement("div");
  bolha.className = "chat-bolha chat-bolha-assistente";
  bolha.append(conteudo);
  el.historico.append(bolha);
  rolarParaFinal();
}

function rolarParaFinal() {
  el.historico.scrollTop = el.historico.scrollHeight;
}

// Voltar do cronômetro para o chat (nav.js): abre na última mensagem, não
// no topo da conversa.
document.addEventListener("chat:mostrado", () => {
  rolarParaFinal();
  window.scrollTo(0, document.documentElement.scrollHeight);
});

/* ---------------------------- montagem da resposta ------------------------ */

function montarResposta(vm) {
  const frag = document.createDocumentFragment();
  frag.append(criarTitulo(vm.titulo));

  if (vm.mensagem) frag.append(criarParagrafo("busca-mensagem", vm.mensagem));

  if (vm.atividade) {
    // Resultado direto (correspondência exata ou LLM decidiu "encontrada"):
    // um único card, sem repetir a mesma atividade na lista de candidatos
    // abaixo.
    frag.append(criarCardAtividade(vm.atividade, "Atividade selecionada", null, vm.tnpDoConsultor));
  } else if (vm.alternativas.length > 0) {
    // LLM não resolveu para uma única atividade ("ambígua"): mostra as
    // opções que ele considerou plausíveis, não a lista bruta pré-LLM.
    const compacta = vm.alternativas.length > LIMITE_LISTA_ABERTA;
    frag.append(
      criarLista(
        compacta ? `Atividades possíveis (${vm.alternativas.length}) — toque para ver os detalhes` : "Atividades possíveis",
        vm.alternativas,
        compacta ? criarLinhaCompacta : criarCardAtividade,
      ),
    );
  } else if (vm.candidatos.length > 0) {
    // Sem atividade nem alternativas da LLM (LLM indisponível, resposta
    // inválida, ou sem correspondência): candidatos brutos da busca lexical
    // ficam como opção de escolha manual (ver MENSAGENS_ERRO em busca.js).
    frag.append(
      criarLista(
        "Candidatos considerados na busca",
        vm.candidatos,
        (candidato) => criarCardAtividade(candidato.atividade, null, candidato.termos_casados),
      ),
    );
  }

  return frag;
}

function criarTitulo(texto) {
  const h3 = document.createElement("h3");
  h3.className = "busca-resultado-titulo";
  h3.textContent = texto;
  return h3;
}

function criarParagrafo(classe, texto) {
  const p = document.createElement("p");
  p.className = classe;
  p.textContent = texto;
  return p;
}

function criarLista(titulo, itens, criarItem) {
  const secao = document.createElement("div");
  secao.className = "busca-lista";

  const h4 = document.createElement("h4");
  h4.textContent = titulo;
  secao.append(h4);

  itens.forEach((item) => secao.append(criarItem(item)));
  return secao;
}

function criarCardAtividade(atividade, rotulo, termosCasados, tnpDoConsultor = false) {
  const card = document.createElement("div");
  card.className = "card-atividade";

  if (rotulo) {
    const tag = document.createElement("span");
    tag.className = "card-atividade-rotulo";
    tag.textContent = rotulo;
    card.append(tag);
  }

  card.append(criarLinha("Atividade", atividade.atividade));
  // Como vai escrito na folha: sem o parêntese explicativo (Guia §1.3).
  card.append(criarLinha("Produto", produtoDaFolha(atividade.produto)));
  card.append(criarLinha("ID oficial", String(atividade.id)));
  // Códigos da folha física (ex.: "19 – TNP: Gestão de Equipe"); valor sem
  // código conhecido aparece como vem da base.
  card.append(
    criarLinha(
      "Classificação",
      tnpDoConsultor
        ? CLASSIFICACAO_TNP_CONSULTOR
        : classificacaoDaFolha(atividade.subgrupo) ?? `${atividade.subgrupo} (${atividade.classificacao})`,
    ),
  );
  card.append(criarLinha("Clientes", clientesDaFolha(atividade.clientes_lista ?? [atividade.clientes])));
  card.append(criarLinha("Segmento", segmentoDaFolha(atividade.segmento_lista ?? [atividade.segmento])));
  card.append(
    criarLinha("Atendimento", atendimentoDaFolha(atividade.atendimento_lista ?? [atividade.atendimento])),
  );

  if (termosCasados && termosCasados.length > 0) {
    card.append(criarLinha("Termos casados", termosCasados.join(", ")));
  }

  return card;
}

// Lista longa (ex.: as 35 atividades de Cartão de Crédito): uma linha por
// atividade; o toque abre o card completo.
function criarLinhaCompacta(atividade) {
  const detalhes = document.createElement("details");
  detalhes.className = "card-compacto";
  const resumo = document.createElement("summary");
  resumo.textContent = atividade.atividade;
  detalhes.append(resumo, criarCardAtividade(atividade));
  return detalhes;
}

function criarLinha(rotulo, valor) {
  const linha = document.createElement("div");
  linha.className = "card-atividade-linha";

  const spanRotulo = document.createElement("span");
  spanRotulo.className = "card-atividade-rotulo-campo";
  spanRotulo.textContent = rotulo;

  const spanValor = document.createElement("span");
  spanValor.className = "card-atividade-valor";
  spanValor.textContent = valor;

  linha.append(spanRotulo, spanValor);
  return linha;
}
