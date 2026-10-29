/**
 * Navegação entre as áreas do app (cronômetro / chat).
 * Módulo independente dos outros dois (cronômetro, busca): só
 * mostra/esconde seções e move o bloco do cronômetro entre o lugar
 * principal e o mini-cronômetro do canto superior direito.
 *
 * O cronômetro (`#view-cronometro`) nunca é recriado — só se move de
 * contêiner via `appendChild`, que preserva o nó (e portanto o estado e os
 * listeners já ligados por `app.js`) intacto. É isso que garante que a
 * medição continua rodando corretamente ao navegar para outra área.
 */

const el = {
  slotPrincipal: document.getElementById("slot-cronometro-principal"),
  slotCompacto: document.getElementById("slot-cronometro-compacto"),
  cronometro: document.getElementById("view-cronometro"),
  views: {
    chat: document.getElementById("view-chat"),
  },
  navBotoes: document.querySelectorAll(".nav-item"),
};

function mostrar(viewAtiva) {
  const cronometroAtivo = viewAtiva === "cronometro";

  el.cronometro.classList.toggle("compacto", !cronometroAtivo);
  (cronometroAtivo ? el.slotPrincipal : el.slotCompacto).appendChild(el.cronometro);
  el.slotCompacto.hidden = cronometroAtivo;

  for (const [nome, secao] of Object.entries(el.views)) {
    secao.hidden = viewAtiva !== nome;
  }

  el.navBotoes.forEach((botao) => {
    const ativo = botao.dataset.view === viewAtiva;
    botao.classList.toggle("ativo", ativo);
    botao.setAttribute("aria-current", ativo ? "page" : "false");
  });

  // Seção acabou de aparecer: o chat rola até a última mensagem.
  if (viewAtiva === "chat") document.dispatchEvent(new Event("chat:mostrado"));
}

el.navBotoes.forEach((botao) => {
  botao.addEventListener("click", () => mostrar(botao.dataset.view));
});

// Service worker: faz o app abrir sem internet (ver sw.js). Falhar aqui
// não quebra nada — o app só não abre offline.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
