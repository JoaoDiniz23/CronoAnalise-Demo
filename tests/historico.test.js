/**
 * Testes do histórico de rodadas finalizadas do cronômetro.
 *
 * `registrarRodadaFinalizada` é pura, testada como as funções de
 * `cronometro.js`. `carregarHistorico`/`salvarHistorico` só são testadas
 * quanto a não travarem quando `localStorage` está ausente ou corrompido -
 * mesma garantia que `app.js` já depende para o estado do cronômetro.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  criarHistorico,
  carregarHistorico,
  salvarHistorico,
  registrarRodadaFinalizada,
  somenteDeHoje,
  ultimaRodadaComLapsVisiveis,
  LAPS_VISIVEIS_APOS_FINALIZAR_MS,
} from "../frontend/historico.js";

test("historico comeca vazio", () => {
  assert.deepEqual(criarHistorico(), []);
});

test("registrarRodadaFinalizada acrescenta ao fim, sem alterar o array original", () => {
  const original = criarHistorico();
  const atualizado = registrarRodadaFinalizada(original, 12_345, 1_700_000_000_000);

  assert.deepEqual(original, []);
  assert.equal(atualizado.length, 1);
  assert.equal(atualizado[0].tempoMs, 12_345);
  assert.equal(atualizado[0].finalizadaEm, 1_700_000_000_000);
});

test("registrarRodadaFinalizada preserva rodadas anteriores ao acrescentar outra", () => {
  let historico = criarHistorico();
  historico = registrarRodadaFinalizada(historico, 1_000, 1);
  historico = registrarRodadaFinalizada(historico, 2_000, 2);

  assert.equal(historico.length, 2);
  assert.equal(historico[0].tempoMs, 1_000);
  assert.equal(historico[1].tempoMs, 2_000);
});

test("registrarRodadaFinalizada ignora tempo invalido (negativo, NaN, nao numero)", () => {
  const historico = criarHistorico();

  assert.deepEqual(registrarRodadaFinalizada(historico, -1, 1), historico);
  assert.deepEqual(registrarRodadaFinalizada(historico, NaN, 1), historico);
  assert.deepEqual(registrarRodadaFinalizada(historico, "12345", 1), historico);
});

test("registrarRodadaFinalizada aceita tempo zero (rodada finalizada sem nunca ter corrido)", () => {
  const historico = registrarRodadaFinalizada(criarHistorico(), 0, 1);
  assert.equal(historico.length, 1);
  assert.equal(historico[0].tempoMs, 0);
});

test("carregarHistorico nunca lanca excecao, mesmo sem localStorage disponivel", () => {
  assert.doesNotThrow(() => carregarHistorico());
  assert.ok(Array.isArray(carregarHistorico()));
});

test("salvarHistorico nunca lanca excecao, mesmo sem localStorage disponivel", () => {
  assert.doesNotThrow(() => salvarHistorico([{ tempoMs: 1, finalizadaEm: 1 }]));
});

test("carregarHistorico com localStorage funcional devolve o que foi salvo", (t) => {
  if (typeof localStorage === "undefined") {
    t.skip("ambiente sem localStorage global (Node antigo)");
    return;
  }
  localStorage.clear();
  salvarHistorico([{ tempoMs: 5_000, finalizadaEm: 10 }]);
  assert.deepEqual(carregarHistorico(), [{ tempoMs: 5_000, finalizadaEm: 10 }]);
  localStorage.clear();
});

test("carregarHistorico descarta entradas corrompidas, mantendo as validas", (t) => {
  if (typeof localStorage === "undefined") {
    t.skip("ambiente sem localStorage global (Node antigo)");
    return;
  }
  localStorage.setItem(
    "cronoanalise:historico:v1",
    JSON.stringify([{ tempoMs: 1_000, finalizadaEm: 1 }, { tempoMs: -5 }, "lixo", null]),
  );
  assert.deepEqual(carregarHistorico(), [{ tempoMs: 1_000, finalizadaEm: 1 }]);
  localStorage.clear();
});

test("carregarHistorico devolve vazio se o conteudo salvo nao for um array", (t) => {
  if (typeof localStorage === "undefined") {
    t.skip("ambiente sem localStorage global (Node antigo)");
    return;
  }
  localStorage.setItem("cronoanalise:historico:v1", JSON.stringify({ nao: "e array" }));
  assert.deepEqual(carregarHistorico(), []);
  localStorage.clear();
});

test("somenteDeHoje apaga rodadas de dias anteriores e mantém as de hoje", () => {
  const agora = new Date(2026, 9, 6, 9, 0).getTime();          // 06/10, 9h
  const ontem = new Date(2026, 9, 5, 17, 30).getTime();         // 05/10, 17h30
  const hojeCedo = new Date(2026, 9, 6, 0, 5).getTime();        // 06/10, 0h05
  const historico = [
    { tempoMs: 1_000, finalizadaEm: ontem },
    { tempoMs: 2_000, finalizadaEm: hojeCedo },
    { tempoMs: 3_000 }, // sem data: não dá para saber o dia, sai
  ];
  assert.deepEqual(somenteDeHoje(historico, agora), [{ tempoMs: 2_000, finalizadaEm: hojeCedo }]);
});

test("registrarRodadaFinalizada guarda as laps da rodada", () => {
  const laps = [10_000, 25_000];
  const historico = registrarRodadaFinalizada(criarHistorico(), 30_000, 5, laps);
  assert.deepEqual(historico[0].laps, [10_000, 25_000]);
  laps.push(1); // cópia, não referência
  assert.equal(historico[0].laps.length, 2);
});

test("ultimaRodadaComLapsVisiveis: mostra por 20 min após finalizar, depois some", () => {
  const T = 1_700_000_000_000;
  const historico = registrarRodadaFinalizada(
    registrarRodadaFinalizada(criarHistorico(), 1_000, T - 1, [500]),
    30_000, T, [10_000, 25_000],
  );
  assert.deepEqual(ultimaRodadaComLapsVisiveis(historico, T + 60_000), { numero: 2, rodada: historico[1] });
  assert.equal(ultimaRodadaComLapsVisiveis(historico, T + LAPS_VISIVEIS_APOS_FINALIZAR_MS), null);
  assert.equal(ultimaRodadaComLapsVisiveis(historico, T - 1), null); // relógio voltou
});

test("ultimaRodadaComLapsVisiveis: rodada sem laps (ou gravada antes desta versão) não aparece", () => {
  assert.equal(ultimaRodadaComLapsVisiveis(registrarRodadaFinalizada([], 1_000, 5), 6), null);
  assert.equal(ultimaRodadaComLapsVisiveis([{ tempoMs: 1_000, finalizadaEm: 5 }], 6), null);
  assert.equal(ultimaRodadaComLapsVisiveis([], 6), null);
});
