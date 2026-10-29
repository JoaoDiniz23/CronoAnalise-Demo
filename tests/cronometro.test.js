/**
 * Testes do nucleo do cronometro de cronoanalise.
 *
 * O nucleo e composto de funcoes puras que recebem o instante atual
 * (`agoraMs`) como parametro, em vez de lerem o relogio por conta propria.
 * Isso permite testar lap sem esperar tempo real passar.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  criarEstado,
  iniciar,
  marcarLap,
  resetar,
  decorrido,
  lapsComIntervalos,
  formatar,
  lapsAoFinalizar,
  restaurarEstado,
  brutoEhValido,
  deveAdotarRecebido,
} from "../frontend/cronometro.js";

// Instante arbitrario em milissegundos, usado como "relogio" dos testes.
const T0 = 1_700_000_000_000;

test("estado inicial: IDLE, zerado e sem laps", () => {
  const estado = criarEstado();

  assert.equal(estado.estado, "IDLE");
  assert.equal(decorrido(estado, T0), 0);
  assert.deepEqual(estado.laps, []);
});

test("iniciar: passa para RUNNING e conta o tempo decorrido", () => {
  const estado = iniciar(criarEstado(), T0);

  assert.equal(estado.estado, "RUNNING");
  assert.equal(decorrido(estado, T0), 0);
  assert.equal(decorrido(estado, T0 + 5_000), 5_000);
});

test("lap: registra o tempo decorrido sem parar o cronometro", () => {
  let estado = iniciar(criarEstado(), T0);
  estado = marcarLap(estado, T0 + 14_320);

  assert.equal(estado.estado, "RUNNING");
  assert.deepEqual(estado.laps, [14_320]);
  // Cronometro continua correndo depois do lap.
  assert.equal(decorrido(estado, T0 + 20_000), 20_000);
});

test("multiplos laps: guarda o total desde o inicio e deriva o intervalo entre laps", () => {
  let estado = iniciar(criarEstado(), T0);
  estado = marcarLap(estado, T0 + 14_320);
  estado = marcarLap(estado, T0 + 27_810);
  estado = marcarLap(estado, T0 + 43_170);

  assert.deepEqual(estado.laps, [14_320, 27_810, 43_170]);
  assert.deepEqual(lapsComIntervalos(estado), [
    { numero: 1, total: 14_320, intervalo: 14_000 },
    { numero: 2, total: 27_810, intervalo: 13_000 },
    { numero: 3, total: 43_170, intervalo: 16_000 },
  ]);
});

test("lapsComIntervalos: soma dos intervalos exibidos bate com o total exibido", () => {
  let estado = iniciar(criarEstado(), T0);
  for (let i = 1; i <= 3; i++) estado = marcarLap(estado, T0 + i * 10_600);
  const laps = lapsComIntervalos(estado);
  const soma = laps.reduce((acc, l) => acc + l.intervalo, 0);
  assert.equal(formatar(soma), formatar(laps.at(-1).total)); // 00:31
});

test("resetar: volta ao estado inicial e descarta os laps", () => {
  let estado = iniciar(criarEstado(), T0);
  estado = marcarLap(estado, T0 + 5_000);
  estado = resetar();

  assert.equal(estado.estado, "IDLE");
  assert.equal(decorrido(estado, T0 + 99_000), 0);
  assert.deepEqual(estado.laps, []);
});

test("transicoes invalidas nao alteram o estado", () => {
  const parado = criarEstado();
  // Lap parado nao faz nada (o botao fica escondido na UI, isto e a rede
  // de seguranca da logica).
  assert.deepEqual(marcarLap(parado, T0), parado);

  const rodando = iniciar(parado, T0);
  assert.deepEqual(iniciar(rodando, T0 + 1_000), rodando);
});

test("formatar: MM:SS sem centesimos, com hora so quando passa de 1h", () => {
  assert.equal(formatar(0), "00:00");
  assert.equal(formatar(14_320), "00:14");
  assert.equal(formatar(14_999), "00:14");
  assert.equal(formatar(90_000), "01:30");
  assert.equal(formatar(3_600_000), "1:00:00");
});

test("restaurarEstado: aceita estado valido e descarta lixo", () => {
  const rodando = iniciar(criarEstado(), T0);

  assert.deepEqual(restaurarEstado(JSON.parse(JSON.stringify(rodando))), rodando);
  // Qualquer coisa corrompida/inesperada volta ao estado inicial em vez de
  // quebrar a aplicacao no carregamento.
  assert.deepEqual(restaurarEstado(null), criarEstado());
  assert.deepEqual(restaurarEstado({ estado: "VOANDO" }), criarEstado());
  assert.deepEqual(restaurarEstado({ estado: "RUNNING" }), criarEstado());
});

test("decorrido: nunca fica negativo se o relogio do sistema andar para tras", () => {
  const estado = iniciar(criarEstado(), T0);
  assert.equal(decorrido(estado, T0 - 5_000), 0);
});

test("brutoEhValido: mesma validacao usada por restaurarEstado, exposta a parte", () => {
  const rodando = iniciar(criarEstado(), T0);

  assert.equal(brutoEhValido(JSON.parse(JSON.stringify(rodando))), true);
  assert.equal(brutoEhValido(null), false);
  assert.equal(brutoEhValido({ estado: "VOANDO" }), false);
  assert.equal(brutoEhValido({ estado: "RUNNING" }), false);
});

test("deveAdotarRecebido: arbitragem por timestamp entre abas", () => {
  // sem timestamp local (retrocompat) -> um recebido valido sempre vence
  assert.equal(deveAdotarRecebido(null, 100), true);
  // recebido sem timestamp valido -> nunca adota
  assert.equal(deveAdotarRecebido(100, null), false);
  assert.equal(deveAdotarRecebido(100, NaN), false);
  // recebido mais novo -> adota
  assert.equal(deveAdotarRecebido(100, 200), true);
  // recebido mais velho -> mantem o local
  assert.equal(deveAdotarRecebido(200, 100), false);
  // empate -> mantem o local (evita ciclo de readocao)
  assert.equal(deveAdotarRecebido(100, 100), false);
});

test("lapsAoFinalizar: o trecho depois da ultima lap vira a lap final", () => {
  let estado = iniciar(criarEstado(), T0);
  estado = marcarLap(estado, T0 + 10_000);
  estado = marcarLap(estado, T0 + 25_000);
  assert.deepEqual(lapsAoFinalizar(estado, T0 + 31_400), [10_000, 25_000, 31_400]);
  // soma das laps exibidas = total exibido
  const laps = lapsComIntervalos({ laps: lapsAoFinalizar(estado, T0 + 31_400) });
  assert.equal(formatar(laps.reduce((a, l) => a + l.intervalo, 0)), formatar(31_400));
});

test("lapsAoFinalizar: sem lap nenhuma, a medicao inteira vira a Lap 1", () => {
  const estado = iniciar(criarEstado(), T0);
  assert.deepEqual(lapsAoFinalizar(estado, T0 + 5_000), [5_000]);
});

test("lapsAoFinalizar: finalizar no mesmo segundo da ultima lap nao cria lap vazia", () => {
  const estado = marcarLap(iniciar(criarEstado(), T0), T0 + 10_200);
  assert.deepEqual(lapsAoFinalizar(estado, T0 + 10_900), [10_200]);
});
