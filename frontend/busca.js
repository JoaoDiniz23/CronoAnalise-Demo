/**
 * Nucleo puro da busca de atividades (Fase 1C).
 *
 * Este modulo so transforma dados - nunca toca no DOM nem chama `fetch`.
 * A ligacao com a tela fica em `chat-app.js`, no mesmo espirito de
 * `cronometro.js` (nucleo puro e testavel) + `app.js` (binding), mas em
 * arquivos proprios: cronometro e busca de atividades sao dois modulos
 * independentes do produto (ver CLAUDE.md) e nao devem compartilhar
 * estado nem se importar um ao outro.
 *
 * Principio de seguranca que sustenta `interpretarResultado`: quando o
 * status vem de uma falha do LLM (`llm_indisponivel`, `resposta_invalida`),
 * a mensagem mostrada ao consultor NUNCA repete `erro.mensagem` (pode
 * conter texto tecnico do provedor, ex.: "429 RESOURCE_EXHAUSTED: ..."),
 * so uma mensagem fixa por `erro.tipo`. `atividade`, `alternativas` e
 * `candidatos` sempre vem prontos da API (dado oficial ou vazio) - este
 * modulo so decide COMO mostrar, nunca inventa um resultado.
 */

const TITULOS_STATUS = {
  encontrada: "Atividade encontrada",
  ambigua: "Mais de uma atividade possível",
  sem_correspondencia: "Nenhuma atividade oficial corresponde",
  entrada_insuficiente: "Descrição insuficiente",
  llm_indisponivel: "Busca automática indisponível",
  resposta_invalida: "Não foi possível confirmar automaticamente",
};

const TITULO_PADRAO = "Resultado da busca";

// Mensagem fixa por `erro.tipo` (ver backend/busca/llm.py e validador.py) -
// nunca `erro.mensagem`, que pode trazer texto tecnico do provedor do LLM.
const MENSAGENS_ERRO = {
  chave_ausente: "A busca automática não está configurada neste ambiente. Escolha manualmente entre as opções abaixo.",
  chave_invalida: "A busca automática está indisponível no momento. Escolha manualmente entre as opções abaixo.",
  quota_ou_limite: "O limite de uso da busca automática foi atingido. Tente novamente em instantes ou escolha manualmente.",
  timeout: "A busca automática demorou demais para responder. Tente novamente.",
  api_indisponivel: "A busca automática está indisponível no momento. Escolha manualmente entre as opções abaixo.",
  modelo_indisponivel: "A busca automática está indisponível no momento. Escolha manualmente entre as opções abaixo.",
  erro_llm: "A busca automática está indisponível no momento. Escolha manualmente entre as opções abaixo.",
  llm_desativado: "A busca automática não está configurada neste ambiente. Escolha manualmente entre as opções abaixo.",
  resposta_invalida: "Não foi possível confirmar a atividade automaticamente. Escolha manualmente entre as opções abaixo.",
  sem_internet: "Sem internet (ou sinal fraco demais): estas são as atividades mais parecidas pelas palavras digitadas. Confira antes de usar — a busca inteligente volta quando houver sinal.",
  sessao_expirada: "Para voltar a usar a busca inteligente, entre de novo com a senha. Enquanto isso, estas são as atividades mais parecidas pelas palavras digitadas — confira antes de usar.",
  limite_diario: "O limite diário da busca inteligente foi atingido. Estas são as atividades mais parecidas pelas palavras digitadas — confira antes de usar.",
  limite_pessoal: "Você já usou todas as buscas inteligentes de hoje. Estas são as atividades mais parecidas pelas palavras digitadas — confira antes de usar. Nome de atividade ou de produto continua respondendo na hora, sem limite, e as buscas inteligentes voltam amanhã.",
  servidor_indisponivel: "O servidor não respondeu. Estas são as atividades mais parecidas pelas palavras digitadas — confira antes de usar.",
};

// Servidor não respondeu: busca feita no próprio celular (`busca-local.js`).
// Cada motivo tem título próprio — "sem internet" só quando for rede mesmo.
const TITULOS_BUSCA_LOCAL = {
  sem_internet: "Sem internet — busca por palavras",
  sessao_expirada: "Sua sessão expirou — entre de novo",
  limite_diario: "Limite diário de buscas atingido",
  servidor_indisponivel: "Servidor indisponível — busca por palavras",
  limite_pessoal: "Buscas inteligentes de hoje esgotadas",
};

const MENSAGEM_ERRO_PADRAO =
  "Não foi possível concluir a busca automática agora. Escolha manualmente entre as opções abaixo.";

const STATUS_COM_ERRO_TECNICO = new Set(["llm_indisponivel", "resposta_invalida"]);

/**
 * Corpo da requisicao para `POST /api/atividades/buscar`. So remove
 * espacos nas pontas - qualquer outra validacao (vazio, tamanho maximo)
 * e responsabilidade do backend, para ter uma unica fonte de verdade.
 */
export function montarPedidoBusca(texto) {
  return { texto: (texto ?? "").trim() };
}

/**
 * Transforma um `ResultadoBusca` (JSON da API) num modelo pronto para
 * desenhar na tela: titulo, mensagem segura e os dados oficiais (atividade,
 * alternativas, candidatos) exatamente como vieram da API.
 */
/**
 * Aviso da cota diária de buscas inteligentes (backend/acesso.py): em TODA
 * busca que gastou um uso, para o consultor ver quais buscas contam.
 * `ultimo` = acabou de gastar a última (aviso em destaque). `null` = a
 * busca não usou o LLM, nada a mostrar.
 */
export function avisoDeCota(resultado) {
  const restantes = resultado?.usos_llm_restantes;
  const limite = resultado?.limite_llm_dia;
  if (!resultado?.consumiu_llm || !Number.isInteger(restantes) || !Number.isInteger(limite)) return null;
  if (restantes === 0) {
    return {
      ultimo: true,
      texto: `Esta foi a última das ${limite} buscas inteligentes de hoje. Nome de atividade ou de produto continua na hora, sem limite.`,
    };
  }
  return { ultimo: false, texto: `Busca inteligente · restam ${restantes} de ${limite} hoje.` };
}

export function interpretarResultado(resultado) {
  const titulo =
    TITULOS_BUSCA_LOCAL[resultado.erro?.tipo] ?? TITULOS_STATUS[resultado.status] ?? TITULO_PADRAO;
  const mensagem = STATUS_COM_ERRO_TECNICO.has(resultado.status)
    ? MENSAGENS_ERRO[resultado.erro?.tipo] ?? MENSAGEM_ERRO_PADRAO
    : resultado.justificativa ?? "";

  return {
    titulo,
    mensagem,
    atividade: resultado.atividade ?? null,
    alternativas: resultado.alternativas ?? [],
    candidatos: resultado.candidatos ?? [],
    // Tempo parado do próprio consultor: código 20 na folha (ver chat-app.js).
    tnpDoConsultor: resultado.tnp_do_consultor === true,
  };
}

/* ------------------- momento da pergunta (lap + hora) ------------------- */

/**
 * Lap em que o consultor está, a partir do estado bruto que o cronômetro
 * grava no localStorage (só leitura — o chat não importa o cronômetro).
 * Em andamento com N laps marcadas, está medindo a lap N+1. Parado,
 * ilegível ou ausente → `null`.
 */
export function lapEmAndamento(brutoCronometro) {
  if (!brutoCronometro || brutoCronometro.estado !== "RUNNING" || !Array.isArray(brutoCronometro.laps)) return null;
  return brutoCronometro.laps.length + 1;
}

/** Rodapé da resposta: "Lap 4 · 14:32", ou só "14:32" sem medição rodando. */
export function textoMomento(momento) {
  if (!momento || typeof momento.emMs !== "number") return null;
  const hora = new Date(momento.emMs).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return Number.isInteger(momento.lap) ? `Lap ${momento.lap} · ${hora}` : hora;
}

/* ------------------------- histórico da conversa ------------------------- */

// Buscas guardadas na tela: acima disso, some a mais antiga (uma a uma).
export const MAX_BUSCAS_CONVERSA = 30;

/** "AAAA-MM-DD" no fuso do celular: a conversa vale só no dia. */
export function diaLocal(ms) {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Só as entradas de hoje, válidas, e no máximo as últimas MAX_BUSCAS_CONVERSA. */
export function podarConversa(entradas, hoje) {
  if (!Array.isArray(entradas)) return [];
  return entradas
    .filter((e) => e && e.dia === hoje && typeof e.texto === "string" && e.resposta)
    .slice(-MAX_BUSCAS_CONVERSA);
}

// Sinal fraco: depois disso, desiste do servidor e mostra a busca local.
// A 1ª busca da sessão, ou depois de 5 min sem buscar (o cache do LLM
// expira), leva mais: servidor pode estar acordando + cache sendo regravado.
const TEMPO_SERVIDOR_MS = 8000;
const TEMPO_SERVIDOR_FRIO_MS = 15000;
const CACHE_LLM_EXPIRA_MS = 5 * 60_000;

export function tempoMaxServidorMs(ultimaBuscaServidorMs, agoraMs) {
  const frio = ultimaBuscaServidorMs == null || agoraMs - ultimaBuscaServidorMs >= CACHE_LLM_EXPIRA_MS;
  return frio ? TEMPO_SERVIDOR_FRIO_MS : TEMPO_SERVIDOR_MS;
}
