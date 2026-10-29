/**
 * Testes das funcoes puras de interpretacao do resultado da busca de
 * atividades (Fase 1C).
 *
 * So testamos aqui a transformacao de `ResultadoBusca` (JSON vindo de
 * `POST /api/atividades/buscar`) em dados prontos para desenhar na tela.
 * Nao ha DOM nem fetch neste arquivo - a ligacao com a tela e testada
 * manualmente (ver relatorio da Fase 1C), como ja e o padrao deste
 * projeto para o cronometro (nucleo puro + binding).
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  MAX_BUSCAS_CONVERSA,
  avisoDeCota,
  diaLocal,
  interpretarResultado,
  montarPedidoBusca,
  podarConversa,
  tempoMaxServidorMs,
} from "../frontend/busca.js";

function atividade(id) {
  return {
    id,
    atividade: "Saque",
    produto: "Conta Corrente",
    subgrupo: "Movimentacao",
    clientes: "Pessoa Fisica",
    segmento: "Varejo",
    atendimento: "Presencial",
    classificacao: "1",
    clientes_lista: ["Pessoa Fisica"],
    segmento_lista: ["Varejo"],
    atendimento_lista: ["Presencial"],
  };
}

test("encontrada: titulo de sucesso e a atividade oficial no resultado", () => {
  const resultado = {
    texto_original: "cliente sacou no caixa",
    status: "encontrada",
    origem: "llm",
    atividade: atividade(42),
    alternativas: [],
    candidatos: [{ atividade: atividade(42), pontuacao: 3.1, termos_casados: ["sacou"] }],
    justificativa: "descricao corresponde ao saque em conta corrente",
    erro: null,
    modelo: "claude-haiku-4-5-20251001",
  };

  const vm = interpretarResultado(resultado);

  assert.equal(vm.titulo, "Atividade encontrada");
  assert.equal(vm.mensagem, "descricao corresponde ao saque em conta corrente");
  assert.deepEqual(vm.atividade, atividade(42));
  assert.deepEqual(vm.alternativas, []);
  assert.equal(vm.candidatos.length, 1);
});

test("ambigua: traz as alternativas, sem atividade unica", () => {
  const resultado = {
    texto_original: "duvida sobre consignado",
    status: "ambigua",
    origem: "llm",
    atividade: null,
    alternativas: [atividade(1), atividade(2)],
    candidatos: [],
    justificativa: "duas atividades plausiveis",
    erro: null,
    modelo: "claude-haiku-4-5-20251001",
  };

  const vm = interpretarResultado(resultado);

  assert.equal(vm.titulo, "Mais de uma atividade possível");
  assert.equal(vm.atividade, null);
  assert.equal(vm.alternativas.length, 2);
});

test("sem_correspondencia: mensagem explicita, nenhuma atividade inventada", () => {
  const resultado = {
    texto_original: "foi tomar um cafe",
    status: "sem_correspondencia",
    origem: "busca",
    atividade: null,
    alternativas: [],
    candidatos: [],
    justificativa: "nenhuma palavra da descrição aparece na base oficial de atividades",
    erro: null,
    modelo: null,
  };

  const vm = interpretarResultado(resultado);

  assert.equal(vm.titulo, "Nenhuma atividade oficial corresponde");
  assert.equal(vm.atividade, null);
  assert.equal(vm.mensagem, "nenhuma palavra da descrição aparece na base oficial de atividades");
});

test("entrada_insuficiente: usa a justificativa do proprio servico", () => {
  const resultado = {
    texto_original: "",
    status: "entrada_insuficiente",
    origem: null,
    atividade: null,
    alternativas: [],
    candidatos: [],
    justificativa: "descrição vazia",
    erro: null,
    modelo: null,
  };

  const vm = interpretarResultado(resultado);

  assert.equal(vm.titulo, "Descrição insuficiente");
  assert.equal(vm.mensagem, "descrição vazia");
});

test("llm_indisponivel: mensagem amigavel por tipo de erro, nunca o detalhe interno", () => {
  const resultado = {
    texto_original: "cliente pediu segunda via do cartao",
    status: "llm_indisponivel",
    origem: null,
    atividade: null,
    alternativas: [],
    candidatos: [{ atividade: atividade(7), pontuacao: 1.0, termos_casados: ["cartao"] }],
    justificativa: null,
    erro: { tipo: "quota_ou_limite", mensagem: "429 RESOURCE_EXHAUSTED: quota exceeded for project X" },
    modelo: "claude-haiku-4-5-20251001",
  };

  const vm = interpretarResultado(resultado);

  assert.equal(vm.titulo, "Busca automática indisponível");
  assert.ok(!vm.mensagem.includes("RESOURCE_EXHAUSTED"));
  assert.ok(!vm.mensagem.includes("429"));
  assert.equal(vm.candidatos.length, 1);
});

test("llm_indisponivel: tipo de erro desconhecido cai numa mensagem generica segura", () => {
  const resultado = {
    texto_original: "x",
    status: "llm_indisponivel",
    origem: null,
    atividade: null,
    alternativas: [],
    candidatos: [],
    justificativa: null,
    erro: { tipo: "algo_novo_ainda_nao_mapeado", mensagem: "traceback interno sensivel" },
    modelo: null,
  };

  const vm = interpretarResultado(resultado);

  assert.ok(!vm.mensagem.includes("traceback"));
});

test("resposta_invalida: mensagem amigavel, candidatos continuam disponiveis para escolha manual", () => {
  const resultado = {
    texto_original: "cliente sacou dinheiro",
    status: "resposta_invalida",
    origem: null,
    atividade: null,
    alternativas: [],
    candidatos: [{ atividade: atividade(9), pontuacao: 2.0, termos_casados: ["sacou"] }],
    justificativa: null,
    erro: { tipo: "resposta_invalida", mensagem: "ID 999 não existe na base oficial" },
    modelo: "claude-haiku-4-5-20251001",
  };

  const vm = interpretarResultado(resultado);

  assert.equal(vm.titulo, "Não foi possível confirmar automaticamente");
  assert.ok(!vm.mensagem.includes("999"));
  assert.equal(vm.candidatos.length, 1);
});

test("montarPedidoBusca: monta o corpo JSON esperado pela rota", () => {
  assert.deepEqual(montarPedidoBusca("  cliente sacou no caixa  "), {
    texto: "cliente sacou no caixa",
  });
});

test("resultado offline (sem internet) tem título e mensagem próprios", () => {
  const vm = interpretarResultado({
    status: "llm_indisponivel",
    erro: { tipo: "sem_internet", mensagem: "" },
    candidatos: [{ atividade: atividade(1), pontuacao: 1, termos_casados: ["saque"] }],
  });
  assert.equal(vm.titulo, "Sem internet — busca por palavras");
  assert.match(vm.mensagem, /^Sem internet/);
  assert.equal(vm.candidatos.length, 1);
});

test("falha que não é de rede não diz 'sem internet'", () => {
  const vm = (tipo) => interpretarResultado({ status: "llm_indisponivel", erro: { tipo, mensagem: "" } });
  assert.equal(vm("sessao_expirada").titulo, "Sua sessão expirou — entre de novo");
  assert.match(vm("sessao_expirada").mensagem, /entre de novo com a senha/);
  assert.equal(vm("limite_diario").titulo, "Limite diário de buscas atingido");
  assert.equal(vm("servidor_indisponivel").titulo, "Servidor indisponível — busca por palavras");
  for (const tipo of ["sessao_expirada", "limite_diario", "servidor_indisponivel"]) {
    assert.doesNotMatch(vm(tipo).mensagem, /Sem internet/);
  }
});

test("resultado de TNP do próprio consultor chega à tela", () => {
  assert.equal(interpretarResultado({ status: "encontrada", tnp_do_consultor: true }).tnpDoConsultor, true);
  assert.equal(interpretarResultado({ status: "encontrada" }).tnpDoConsultor, false);
});

test("aviso da cota aparece em toda busca inteligente, em destaque na última", () => {
  const r = (restantes, consumiu = true) => ({ consumiu_llm: consumiu, usos_llm_restantes: restantes, limite_llm_dia: 50 });
  assert.deepEqual(avisoDeCota(r(45)), { ultimo: false, texto: "Busca inteligente · restam 45 de 50 hoje." });
  assert.deepEqual(avisoDeCota(r(44)), { ultimo: false, texto: "Busca inteligente · restam 44 de 50 hoje." });
  assert.equal(avisoDeCota(r(45, false)), null); // busca que não gastou cota não avisa
  assert.equal(avisoDeCota(r(0)).ultimo, true);
  assert.match(avisoDeCota(r(0)).texto, /última das 50/);
  assert.equal(avisoDeCota({ status: "encontrada" }), null);
});

test("cota esgotada tem título e mensagem próprios", () => {
  const vm = interpretarResultado({ status: "llm_indisponivel", erro: { tipo: "limite_pessoal", mensagem: "" } });
  assert.equal(vm.titulo, "Buscas inteligentes de hoje esgotadas");
  assert.match(vm.mensagem, /voltam amanhã/);
});

/* ------------------------- histórico da conversa ------------------------- */

const HOJE = diaLocal(new Date(2026, 8, 25, 10).getTime());
const entrada = (n, dia = HOJE) => ({ dia, texto: `busca ${n}`, resposta: { tipo: "api", resultado: {} } });

test("conversa guarda só as últimas MAX_BUSCAS_CONVERSA buscas, na ordem", () => {
  const entradas = Array.from({ length: MAX_BUSCAS_CONVERSA + 5 }, (_, n) => entrada(n));
  const podada = podarConversa(entradas, HOJE);
  assert.equal(podada.length, MAX_BUSCAS_CONVERSA);
  assert.equal(podada[0].texto, "busca 5");
  assert.equal(podada.at(-1).texto, `busca ${MAX_BUSCAS_CONVERSA + 4}`);
});

test("conversa de outro dia é apagada", () => {
  const ontem = diaLocal(new Date(2026, 8, 24, 23, 59).getTime());
  assert.deepEqual(podarConversa([entrada(1, ontem), entrada(2)], HOJE).map((e) => e.texto), ["busca 2"]);
});

test("conversa ilegível vira vazia", () => {
  assert.deepEqual(podarConversa(null, HOJE), []);
  assert.deepEqual(podarConversa([null, { dia: HOJE }], HOJE), []);
});

test("1ª busca da sessão (ou após 5 min parado) espera mais pelo servidor", () => {
  const agora = 1_000_000_000;
  assert.equal(tempoMaxServidorMs(null, agora), 15000);
  assert.equal(tempoMaxServidorMs(agora - 60_000, agora), 8000);
  assert.equal(tempoMaxServidorMs(agora - 5 * 60_000, agora), 15000);
});

test("lapEmAndamento: medindo com N laps marcadas está na lap N+1; parado ou lixo → null", async () => {
  const { lapEmAndamento } = await import("../frontend/busca.js");
  assert.equal(lapEmAndamento({ estado: "RUNNING", laps: [] }), 1);
  assert.equal(lapEmAndamento({ estado: "RUNNING", laps: [1, 2, 3] }), 4);
  assert.equal(lapEmAndamento({ estado: "IDLE", laps: [] }), null);
  assert.equal(lapEmAndamento(null), null);
  assert.equal(lapEmAndamento({ estado: "RUNNING" }), null);
});

test("textoMomento: 'Lap N · HH:MM', só a hora sem medição, null sem dado", async () => {
  const { textoMomento } = await import("../frontend/busca.js");
  const ms = new Date(2026, 8, 29, 14, 32).getTime();
  assert.equal(textoMomento({ lap: 4, emMs: ms }), "Lap 4 · 14:32");
  assert.equal(textoMomento({ lap: null, emMs: ms }), "14:32");
  assert.equal(textoMomento(undefined), null);
});
