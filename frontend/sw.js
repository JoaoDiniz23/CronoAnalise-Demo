/**
 * Service worker: faz o app ABRIR sem internet (requisito do usuário,
 * 23/09/2026 — o chatbot precisa funcionar offline; o cronômetro já
 * funcionava).
 *
 * Estratégia "rede primeiro": com sinal, tudo vem do servidor como antes
 * (e o que chegou fica guardado); sem sinal, ou se a rede não responder
 * em TEMPO_REDE_MS, usa a cópia guardada. Assim um deploy novo chega
 * sempre que houver rede — nunca prende versão velha, que era o risco
 * que fez adiar o service worker em 22/09.
 *
 * Não intercepta /api/*: a base de atividades para a busca offline fica
 * no localStorage (chat-app.js), e a busca com LLM precisa de rede mesmo.
 *
 * VERSAO acompanha o `?v=` do index.html: troque as duas juntas.
 */

const VERSAO = "20260929c";
const CACHE = `cronoanalise-${VERSAO}`;
const TEMPO_REDE_MS = 4000;

const ARQUIVOS = [
  "/",
  `/app.css?v=${VERSAO}`,
  `/app.js?v=${VERSAO}`,
  `/chat-app.js?v=${VERSAO}`,
  `/nav.js?v=${VERSAO}`,
  `/busca.js?v=${VERSAO}`,
  `/busca-local.js?v=${VERSAO}`,
  `/legenda.js?v=${VERSAO}`,
  `/cronometro.js?v=${VERSAO}`,
  `/historico.js?v=${VERSAO}`,
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(
    caches.open(CACHE).then((cache) =>
      // Um a um: um arquivo que falhar não impede guardar os outros.
      Promise.all(ARQUIVOS.map((url) => guardar(cache, url).catch(() => {}))),
    ),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (evento) => {
  const pedido = evento.request;
  const url = new URL(pedido.url);
  if (pedido.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname === "/login") return;
  evento.respondWith(redePrimeiro(pedido));
});

async function guardar(cache, url) {
  const resposta = await fetch(url, { cache: "no-cache" });
  if (podeGuardar(resposta)) await cache.put(url, resposta);
}

// Não guarda erro nem o redirect para /login (sessão vencida): senão o
// app offline abriria a tela de login no lugar do app.
function podeGuardar(resposta) {
  return resposta.ok && !resposta.redirected && resposta.type === "basic";
}

async function redePrimeiro(pedido) {
  const cache = await caches.open(CACHE);
  const daRede = fetch(pedido).then((resposta) => {
    if (podeGuardar(resposta)) cache.put(pedido, resposta.clone());
    return resposta;
  });
  try {
    return await Promise.race([
      daRede,
      new Promise((_, rejeitar) => setTimeout(() => rejeitar(new Error("rede lenta")), TEMPO_REDE_MS)),
    ]);
  } catch {
    const guardada =
      (await cache.match(pedido)) ?? (pedido.mode === "navigate" ? await cache.match("/") : undefined);
    // Sem cópia guardada: espera a rede mesmo (ou falha como falharia sem SW).
    return guardada ?? daRede;
  }
}
