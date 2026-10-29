/**
 * Nucleo do cronometro de cronoanalise.
 *
 * Duas decisoes importantes, que valem para toda a aplicacao:
 *
 * 1. O tempo NAO e contado somando ticks de setInterval. O estado guarda
 *    apenas timestamps (`inicioMs`, com `acumuladoMs` sempre 0 desde que
 *    o Pausar saiu, 22/09); o tempo decorrido e SEMPRE calculado no momento da
 *    leitura: acumulado + (agora - inicio). Se o navegador congelar o loop
 *    de tela por 3 minutos (celular bloqueado, aba em segundo plano), a
 *    proxima leitura ja sai correta sozinha, sem codigo de correcao.
 *
 * 2. Nenhuma funcao aqui le o relogio por conta propria - o instante atual
 *    (`agoraMs`) entra sempre como parametro. Isso mantem o nucleo puro e
 *    testavel sem esperar tempo real passar.
 *
 * O relogio usado pela aplicacao e `Date.now()` (relogio de parede), e nao
 * `performance.now()`. Motivo: o estado e persistido em localStorage para
 * sobreviver ao navegador matar a aba (acontece no iOS com a tela
 * bloqueada), e um valor de `performance.now()` salvo nao significa mais
 * nada depois que a pagina recarrega - ele volta a zero. O preco dessa
 * escolha e ficar sujeito a ajustes do relogio do sistema (NTP), que em
 * celular sao raros e da ordem de milissegundos.
 */

const IDLE = "IDLE";
const RUNNING = "RUNNING";

export function criarEstado() {
  return { estado: IDLE, inicioMs: null, acumuladoMs: 0, laps: [] };
}

export function resetar() {
  return criarEstado();
}

export function iniciar(estado, agoraMs) {
  if (estado.estado !== IDLE) return estado;
  return { ...estado, estado: RUNNING, inicioMs: agoraMs };
}

export function marcarLap(estado, agoraMs) {
  if (estado.estado !== RUNNING) return estado;
  return { ...estado, laps: [...estado.laps, decorrido(estado, agoraMs)] };
}

export function decorrido(estado, agoraMs) {
  if (estado.estado !== RUNNING) return estado.acumuladoMs;
  // Math.max contra o relogio do sistema sendo atrasado manualmente
  // enquanto o cronometro roda - nao corrige o caso geral (o projeto usa
  // Date.now() de proposito, ver cabecalho do arquivo), so evita mostrar
  // um tempo negativo.
  return Math.max(0, estado.acumuladoMs + (agoraMs - estado.inicioMs));
}

/**
 * Os laps sao guardados como tempo TOTAL desde o inicio da medicao - uma
 * unica fonte de verdade, sem risco de acumular erro de arredondamento.
 * O intervalo entre um lap e o anterior (que numa cronoanalise e a
 * medicao de cada atividade observada) e derivado aqui, na exibicao.
 */
export function lapsComIntervalos(estado) {
  // Intervalo calculado sobre os totais ja truncados em segundos: como a
  // tela mostra so MM:SS, a soma dos intervalos exibidos bate com o total.
  let anterior = 0;
  return estado.laps.map((total, i) => {
    const intervalo = segundosInteiros(total) - anterior;
    anterior = segundosInteiros(total);
    return { numero: i + 1, total, intervalo };
  });
}

/**
 * Laps a arquivar ao Finalizar: o trecho que corria depois da última lap
 * vira a lap final, para a soma das laps fechar com o tempo total
 * (feedback do teste presencial de 29/09). Sem trecho novo (Finalizar logo
 * após uma lap, no mesmo segundo), fica como está.
 */
export function lapsAoFinalizar(estado, agoraMs) {
  const total = decorrido(estado, agoraMs);
  const ultima = estado.laps.at(-1) ?? 0;
  return segundosInteiros(total) > segundosInteiros(ultima) ? [...estado.laps, total] : [...estado.laps];
}

function segundosInteiros(ms) {
  return Math.floor(ms / 1000) * 1000;
}

// So minutos e segundos (sem centesimos): decisao do usuario apos o teste
// presencial de 29/09 - centesimos eram confundidos com segundos na folha.
export function formatar(ms) {
  const totalSegundos = Math.floor(ms / 1000);
  const segundos = totalSegundos % 60;
  const minutos = Math.floor(totalSegundos / 60) % 60;
  const horas = Math.floor(totalSegundos / 3600);

  const dd = (n) => String(n).padStart(2, "0");
  const base = `${dd(minutos)}:${dd(segundos)}`;
  return horas > 0 ? `${horas}:${base}` : base;
}

/**
 * Verifica se um valor bruto (ja vindo de JSON.parse) tem o formato de um
 * estado de cronometro valido. Extraida de `restaurarEstado` para que
 * `app.js` consiga distinguir "nunca salvou nada" (bruto === null, normal)
 * de "salvou algo e nao deu para usar" (bruto existe e e invalido) - a
 * segunda situacao merece avisar o usuario, a primeira nao.
 */
export function brutoEhValido(bruto) {
  if (!bruto || typeof bruto !== "object") return false;

  const { estado, inicioMs, acumuladoMs, laps } = bruto;
  const estadoValido = [IDLE, RUNNING].includes(estado);
  const inicioValido = estado === RUNNING
    ? typeof inicioMs === "number" && Number.isFinite(inicioMs)
    : inicioMs === null;
  const acumuladoValido = typeof acumuladoMs === "number" &&
    Number.isFinite(acumuladoMs) && acumuladoMs >= 0;
  const lapsValidos = Array.isArray(laps) &&
    laps.every((l) => typeof l === "number" && Number.isFinite(l));

  return estadoValido && inicioValido && acumuladoValido && lapsValidos;
}

/**
 * Le de volta um estado vindo do localStorage. Qualquer coisa corrompida,
 * incompleta ou de uma versao antiga volta como estado inicial, em vez de
 * quebrar a aplicacao no carregamento (o usuario nao teria como se
 * recuperar disso a nao ser limpando os dados do site).
 */
export function restaurarEstado(bruto) {
  if (!brutoEhValido(bruto)) return criarEstado();
  const { estado, inicioMs, acumuladoMs, laps } = bruto;
  return { estado, inicioMs, acumuladoMs, laps: [...laps] };
}

/**
 * Arbitragem entre abas: decide se um estado recebido de outra aba (via
 * evento `storage`) deve substituir o estado local, comparando os
 * timestamps `atualizadoEm` de cada um. Pura, sem tocar em `estado`, em
 * `bruto` nem em storage - so dois numeros.
 *
 * Empate fica com o local (comparacao estrita, `>`) para nao entrar num
 * ciclo de readocao quando duas escritas caem no mesmo milissegundo.
 */
export function deveAdotarRecebido(atualAtualizadoEm, recebidoAtualizadoEm) {
  if (typeof recebidoAtualizadoEm !== "number" || !Number.isFinite(recebidoAtualizadoEm)) {
    return false; // nunca adota um valor sem timestamp valido
  }
  if (typeof atualAtualizadoEm !== "number" || !Number.isFinite(atualAtualizadoEm)) {
    return true; // estado local sem timestamp (retrocompat) sempre perde
  }
  return recebidoAtualizadoEm > atualAtualizadoEm;
}
