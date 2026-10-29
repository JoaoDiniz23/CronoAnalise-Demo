/**
 * Histórico de rodadas finalizadas do cronômetro.
 *
 * Deliberadamente separado de `cronometro.js`: o núcleo do cronômetro não
 * sabe nada sobre "rodadas" nem sobre persistência de histórico, só mede o
 * tempo de UMA medição corrente. Este módulo guarda o que já foi finalizado,
 * para que confirmar "Zerar tudo" não apague o tempo já medido - só a
 * medição corrente é zerada; a rodada anterior fica registrada aqui.
 *
 * Mesma decisão de robustez de `cronometro.js`/`app.js`: localStorage pode
 * estar indisponível ou conter lixo, e isso nunca pode travar a aplicação.
 */

const CHAVE_HISTORICO = "cronoanalise:historico:v1";

export function criarHistorico() {
  return [];
}

export function carregarHistorico() {
  try {
    const bruto = JSON.parse(localStorage.getItem(CHAVE_HISTORICO));
    if (!Array.isArray(bruto)) return criarHistorico();
    return bruto.filter(rodadaValida);
  } catch {
    return criarHistorico();
  }
}

export function salvarHistorico(historico) {
  try {
    localStorage.setItem(CHAVE_HISTORICO, JSON.stringify(historico));
  } catch {
    // Não poder salvar não pode travar a aplicação - a rodada finalizada
    // continua visível em memória, só não sobrevive a um reload.
  }
}

/**
 * Acrescenta uma rodada finalizada ao fim do histórico. `tempoMs` é o tempo
 * decorrido da medição no instante da confirmação (já calculado por quem
 * chama, via `decorrido()` do cronômetro - este módulo não lê relógio).
 */
export function registrarRodadaFinalizada(historico, tempoMs, finalizadaEmMs, laps = []) {
  if (typeof tempoMs !== "number" || !Number.isFinite(tempoMs) || tempoMs < 0) {
    return historico;
  }
  return [...historico, { tempoMs, finalizadaEm: finalizadaEmMs, laps: [...laps] }];
}

// Depois de Finalizar, as laps da rodada seguem na tela por este tempo
// (decisão do usuário após o teste presencial de 29/09): o consultor
// precisa ver os minutos de cada lap para preencher a folha.
export const LAPS_VISIVEIS_APOS_FINALIZAR_MS = 20 * 60 * 1000;

/**
 * A última rodada finalizada, se ainda estiver dentro da janela de 20 min e
 * tiver laps; senão `null`. Conta pela hora gravada, então vale mesmo com o
 * app fechado ou o celular bloqueado nesse meio-tempo.
 */
export function ultimaRodadaComLapsVisiveis(historico, agoraMs) {
  const numero = historico.length;
  const rodada = historico[numero - 1];
  if (!rodada || !Array.isArray(rodada.laps) || rodada.laps.length === 0) return null;
  if (!rodada.laps.every((l) => typeof l === "number" && Number.isFinite(l))) return null;
  const idade = agoraMs - rodada.finalizadaEm;
  if (!(idade >= 0 && idade < LAPS_VISIVEIS_APOS_FINALIZAR_MS)) return null;
  return { numero, rodada };
}

/**
 * Só as rodadas finalizadas no MESMO dia (calendário do celular) de
 * `agoraMs`. Decisão do usuário (23/09/2026): o histórico de dias
 * anteriores é apagado — cada dia de campo começa limpo. A medição em
 * andamento não mora aqui, então nunca é afetada.
 */
export function somenteDeHoje(historico, agoraMs) {
  const hoje = new Date(agoraMs).toDateString();
  return historico.filter(
    (rodada) => typeof rodada.finalizadaEm === "number" && new Date(rodada.finalizadaEm).toDateString() === hoje,
  );
}

function rodadaValida(rodada) {
  return (
    rodada &&
    typeof rodada === "object" &&
    typeof rodada.tempoMs === "number" &&
    Number.isFinite(rodada.tempoMs) &&
    rodada.tempoMs >= 0
  );
}
