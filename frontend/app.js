/**
 * Ligacao entre o nucleo do cronometro e a tela.
 *
 * Regra que sustenta a precisao: esta camada NUNCA calcula nem incrementa
 * tempo. Ela so chama `decorrido(estado, Date.now())` e desenha o
 * resultado. O loop de 100ms existe apenas para redesenhar - se o
 * navegador congelar esse loop (celular bloqueado, aba em segundo plano),
 * nada se perde: o proximo desenho ja sai com o valor certo.
 */

import {
  criarEstado,
  iniciar,
  marcarLap,
  resetar,
  decorrido,
  lapsComIntervalos,
  lapsAoFinalizar,
  formatar,
  restaurarEstado,
  brutoEhValido,
  deveAdotarRecebido,
} from "./cronometro.js?v=20260929c";
import {
  carregarHistorico,
  salvarHistorico,
  registrarRodadaFinalizada,
  somenteDeHoje,
  ultimaRodadaComLapsVisiveis,
  LAPS_VISIVEIS_APOS_FINALIZAR_MS,
} from "./historico.js?v=20260929c";

const CHAVE_ARMAZENAMENTO = "cronoanalise:cronometro:v1";
const INTERVALO_DESENHO_MS = 100;

const el = {
  tempo: document.getElementById("tempo"),
  situacao: document.getElementById("situacao"),
  avisoRecuperacao: document.getElementById("aviso-recuperacao"),
  fecharAviso: document.getElementById("btn-fechar-aviso"),
  iniciar: document.getElementById("btn-iniciar"),
  lap: document.getElementById("btn-lap"),
  resetar: document.getElementById("btn-resetar"),
  lapAviso: document.getElementById("lap-aviso"),
  lapsCabecalho: document.getElementById("laps-cabecalho"),
  lapsLegenda: document.getElementById("laps-legenda"),
  lapsLista: document.getElementById("laps-lista"),
  historico: document.getElementById("historico"),
  historicoLista: document.getElementById("historico-lista"),
  confirmacao: document.getElementById("confirmacao"),
  confirmacaoDetalhe: document.getElementById("confirmacao-detalhe"),
  cancelarReset: document.getElementById("btn-cancelar-reset"),
  confirmarReset: document.getElementById("btn-confirmar-reset"),
};

const SITUACAO = {
  IDLE: "Pronto para iniciar",
  RUNNING: "Medindo…",
};

let { estado, atualizadoEm, recuperacaoFalhou } = carregar();
let historico = limparDiasAnteriores(carregarHistorico());

// Histórico só do dia: apaga (e regrava) rodadas de dias anteriores.
function limparDiasAnteriores(lista) {
  const deHoje = somenteDeHoje(lista, Date.now());
  if (deHoje.length !== lista.length) salvarHistorico(deHoje);
  return deHoje;
}
let timerDesenho = null;

/* ----------------------------- persistencia ----------------------------- */

/**
 * Le o estado bruto do localStorage e distingue "nunca salvou nada" (bruto
 * === null, situacao normal) de "salvou algo e nao deu para usar" (bruto
 * existe mas e invalido, ou a leitura/parse falhou) - a segunda situacao
 * liga `recuperacaoFalhou`, para a interface avisar o usuario em vez de
 * simplesmente mostrar 00:00 sem explicacao.
 */
function carregar() {
  let bruto = null;
  try {
    bruto = JSON.parse(localStorage.getItem(CHAVE_ARMAZENAMENTO));
  } catch {
    // localStorage indisponivel (aba privada em alguns navegadores) ou
    // JSON corrompido: comeca do zero em vez de travar a aplicacao.
    return { estado: criarEstado(), atualizadoEm: null, recuperacaoFalhou: true };
  }
  if (bruto !== null && !brutoEhValido(bruto)) {
    return { estado: criarEstado(), atualizadoEm: null, recuperacaoFalhou: true };
  }
  return {
    estado: restaurarEstado(bruto),
    atualizadoEm: atualizadoEmDoBruto(bruto),
    recuperacaoFalhou: false,
  };
}

function atualizadoEmDoBruto(bruto) {
  return bruto && typeof bruto.atualizadoEm === "number" && Number.isFinite(bruto.atualizadoEm)
    ? bruto.atualizadoEm
    : null;
}

function salvar() {
  atualizadoEm = Date.now();
  try {
    localStorage.setItem(CHAVE_ARMAZENAMENTO, JSON.stringify({ ...estado, atualizadoEm }));
  } catch {
    // Nao poder salvar nao pode impedir a medicao de continuar: o estado
    // em memoria segue correto, so nao sobrevive a um reload.
  }
}

/**
 * Reconcilia com o que outra aba (do mesmo navegador/contexto de
 * armazenamento) gravou por ultimo. So adota se o timestamp recebido for
 * mais novo que o local (`deveAdotarRecebido`), e so entao rele/redesenha -
 * nunca chama `salvar()` a partir daqui, para nao reempurrar
 * `atualizadoEm` para agora sem necessidade. Chamada tanto pelo evento
 * `storage` quanto pela retomada de foco (`visibilitychange`/`pageshow`),
 * porque uma aba congelada no momento em que a outra escreveu pode perder
 * o evento `storage` e so teria chance de reconciliar ao voltar ao
 * primeiro plano.
 */
function sincronizarComStorage() {
  let bruto;
  try {
    bruto = JSON.parse(localStorage.getItem(CHAVE_ARMAZENAMENTO));
  } catch {
    return;
  }
  const recebidoAtualizadoEm = atualizadoEmDoBruto(bruto);
  if (!deveAdotarRecebido(atualizadoEm, recebidoAtualizadoEm)) return;
  if (!brutoEhValido(bruto)) return; // nunca adota lixo, mesmo que "mais novo"

  estado = restaurarEstado(bruto);
  atualizadoEm = recebidoAtualizadoEm;
  desenhar();
  ajustarLoop();
}

/* ------------------------------ transicoes ------------------------------ */

function aplicar(transicao) {
  estado = transicao(estado, Date.now());
  salvar();
  desenhar();
  ajustarLoop();
}

/* ------------------------------- desenho -------------------------------- */

function desenhar() {
  const emAndamento = estado.estado === "RUNNING";

  el.tempo.textContent = formatar(decorrido(estado, Date.now()));
  el.situacao.textContent = SITUACAO[estado.estado];

  el.iniciar.hidden = estado.estado !== "IDLE";
  el.lap.hidden = !emAndamento;
  el.resetar.hidden = estado.estado === "IDLE";

  desenharLaps();
  desenharHistorico();
}

/**
 * Histórico de rodadas: as já finalizadas (guardadas em `historico.js`) mais
 * a rodada corrente, quando existe algo a mostrar (evita "Rodada 1 - Em
 * andamento - 00:00" antes do consultor sequer apertar Iniciar).
 */
function desenharHistorico() {
  const rodadaCorrenteVisivel = estado.estado !== "IDLE";
  el.historico.hidden = historico.length === 0 && !rodadaCorrenteVisivel;

  const linhas = historico.map((rodada, i) =>
    criarLinhaHistorico(i + 1, rodada.tempoMs, "Finalizada", true),
  );
  if (rodadaCorrenteVisivel) {
    const situacaoCorrente = "Em andamento";
    linhas.push(
      criarLinhaHistorico(
        historico.length + 1,
        decorrido(estado, Date.now()),
        situacaoCorrente,
        false,
      ),
    );
  }
  el.historicoLista.replaceChildren(...linhas);
}

function criarLinhaHistorico(numero, tempoMs, situacao, finalizada) {
  const li = document.createElement("li");
  li.className = finalizada ? "historico-item historico-item-finalizada" : "historico-item";
  li.append(
    criarSpan("historico-rodada", `Rodada ${numero}`),
    criarSpan("historico-tempo", formatar(tempoMs)),
    criarSpan("historico-situacao", situacao),
  );
  return li;
}

/**
 * Laps da medição corrente; com o cronômetro parado, as da última rodada
 * finalizada, por 20 min (`ultimaRodadaComLapsVisiveis`), com uma legenda
 * dizendo de qual rodada são. Iniciar uma medição nova troca a lista.
 */
function desenharLaps() {
  const recente = estado.estado === "IDLE" ? ultimaRodadaComLapsVisiveis(historico, Date.now()) : null;
  const laps = lapsComIntervalos(recente ? { laps: recente.rodada.laps } : estado);
  el.lapsCabecalho.hidden = laps.length === 0;
  el.lapsLegenda.hidden = !recente;
  if (recente) {
    el.lapsLegenda.textContent = `Rodada ${recente.numero} · finalizada às ${horaMinuto(recente.rodada.finalizadaEm)}`;
  }
  agendarFimDosLapsRecentes(recente);

  // Mais recente primeiro: e o que o consultor acabou de registrar.
  el.lapsLista.replaceChildren(
    ...laps.reverse().map(({ numero, total, intervalo }) => {
      const li = document.createElement("li");
      li.append(
        criarSpan("numero", `Lap ${numero}`),
        criarSpan("intervalo", formatar(intervalo)),
        criarSpan("total", formatar(total)),
      );
      return li;
    }),
  );
}

function horaMinuto(ms) {
  return new Date(ms).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

// O loop de desenho para com o cronômetro parado: um timer único redesenha
// quando a janela de 20 min acaba (e ao voltar ao app, via visibilitychange).
let timerFimLapsRecentes = null;
function agendarFimDosLapsRecentes(recente) {
  clearTimeout(timerFimLapsRecentes);
  timerFimLapsRecentes = null;
  if (!recente) return;
  const restante = recente.rodada.finalizadaEm + LAPS_VISIVEIS_APOS_FINALIZAR_MS - Date.now();
  timerFimLapsRecentes = setTimeout(desenhar, Math.max(0, restante) + 50);
}

function criarSpan(classe, texto) {
  const span = document.createElement("span");
  span.className = classe;
  span.textContent = texto;
  return span;
}

/* --------------------------- feedback de toque --------------------------- */

const DURACAO_AVISO_LAP_MS = 500;
const DURACAO_TOQUE_MS = 260;
let timerAvisoLap = null;

/**
 * Confirmacao visivel de que o lap entrou: aviso curto + destaque na linha
 * nova da lista. Importante porque no iPhone nao ha vibracao por site.
 */
function avisarLap() {
  el.lapAviso.textContent = `Lap ${estado.laps.length} registrado`;
  el.lapAviso.hidden = false;
  el.lapsLista.firstElementChild?.classList.add("lap-novo");
  clearTimeout(timerAvisoLap);
  timerAvisoLap = setTimeout(() => { el.lapAviso.hidden = true; }, DURACAO_AVISO_LAP_MS);
}

// Todo botao: "pulso" de cor/tamanho no toque + vibracao curta onde o
// navegador permite (Android; o Safari do iPhone ignora `vibrate`). O
// listener de pointerdown tambem faz o `:active` funcionar no iOS.
document.addEventListener("pointerdown", (evento) => {
  const botao = evento.target.closest(".btn");
  if (!botao) return;
  botao.classList.remove("tocado");
  void botao.offsetWidth; // reinicia a animacao em toques seguidos
  botao.classList.add("tocado");
  setTimeout(() => botao.classList.remove("tocado"), DURACAO_TOQUE_MS);
  try { navigator.vibrate?.(15); } catch { /* sem suporte: so o visual */ }
});

/* ----------------------- loop de atualizacao da tela --------------------- */

function ajustarLoop() {
  const precisaDesenhar = estado.estado === "RUNNING";
  if (precisaDesenhar && timerDesenho === null) {
    timerDesenho = setInterval(desenhar, INTERVALO_DESENHO_MS);
  } else if (!precisaDesenhar && timerDesenho !== null) {
    clearInterval(timerDesenho);
    timerDesenho = null;
  }
}

/* ---------------------------- confirmacao reset -------------------------- */

function abrirConfirmacao() {
  const agora = Date.now();
  const quantidade = lapsAoFinalizar(estado, agora).length;
  const tempo = formatar(decorrido(estado, agora));
  el.confirmacaoDetalhe.textContent =
    `A medição de ${tempo} (${quantidade} lap(s), contando o trecho em andamento) vai para o histórico e o cronômetro volta a zero.`;
  el.confirmacao.hidden = false;
}

function fecharConfirmacao() {
  el.confirmacao.hidden = true;
}

/* -------------------------------- eventos ------------------------------- */

el.iniciar.addEventListener("click", () => aplicar(iniciar));
el.lap.addEventListener("click", () => {
  aplicar(marcarLap);
  avisarLap();
});

el.resetar.addEventListener("click", abrirConfirmacao);
el.cancelarReset.addEventListener("click", fecharConfirmacao);
el.confirmarReset.addEventListener("click", () => {
  fecharConfirmacao();
  // O botão de resetar só aparece fora do estado IDLE (ver desenhar()), ou
  // seja, sempre existe uma medição real para preservar aqui. O tempo é
  // arquivado no histórico ANTES do reset, para que finalizar uma rodada
  // por engano nunca apague o tempo já medido - só zera a medição corrente.
  const agora = Date.now();
  historico = registrarRodadaFinalizada(historico, decorrido(estado, agora), agora, lapsAoFinalizar(estado, agora));
  salvarHistorico(historico);
  aplicar(resetar);
});

if (el.fecharAviso) {
  el.fecharAviso.addEventListener("click", () => {
    el.avisoRecuperacao.hidden = true;
  });
}

// Outra aba do MESMO navegador/contexto de armazenamento gravou por
// ultimo - nunca dispara na propria aba que escreveu (comportamento de
// spec do navegador), entao nao ha risco de loop aqui.
window.addEventListener("storage", (evento) => {
  if (evento.key === CHAVE_ARMAZENAMENTO) sincronizarComStorage();
});

// Ao voltar do segundo plano, redesenha na hora em vez de esperar o
// proximo tick - o numero na tela pode estar congelado ha minutos. Tambem
// relê o localStorage (sincronizarComStorage), porque uma aba que ficou
// congelada enquanto outra escrevia pode ter perdido o evento "storage".
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  sincronizarComStorage();
  // App que ficou aberto de um dia para o outro não recarrega: limpa aqui.
  historico = limparDiasAnteriores(historico);
  desenhar();
});

// Cobre especificamente a retomada via bfcache no iOS Safari: a pagina
// pode voltar de um estado congelado sem passar por um reload completo, e
// a documentacao oficial (web.dev/MDN) recomenda "pageshow" ao lado de
// "visibilitychange" para cobertura completa desse caso. `event.persisted`
// so e true quando a pagina volta do cache, nao num load normal.
window.addEventListener("pageshow", (evento) => {
  if (evento.persisted) sincronizarComStorage();
});

if (recuperacaoFalhou && el.avisoRecuperacao) {
  el.avisoRecuperacao.hidden = false;
}

desenhar();
ajustarLoop();
