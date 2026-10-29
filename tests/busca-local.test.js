/**
 * Paridade da busca offline (`frontend/busca-local.js`) com o backend.
 * O esperado vem do Python (`scripts/gerar_paridade_busca.py`).
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { criarBuscaLocal, radicais } from "../frontend/busca-local.js";

const ler = (caminho) => JSON.parse(readFileSync(new URL(caminho, import.meta.url), "utf-8"));

// Mesma base e mesma ordem que `GET /api/atividades` devolve.
const base = ler("../dados/atividades_padronizadas.json");
const casos = ler("./dados_busca/paridade_busca.json");
const busca = criarBuscaLocal(base);

for (const caso of casos) {
  test(`paridade com o Python: ${JSON.stringify(caso.texto).slice(0, 60)}`, () => {
    assert.deepEqual(radicais(caso.texto), caso.radicais, "radicais");
    assert.equal(busca.corrigir(caso.texto), caso.corrigido, "correção de digitação");
    const exata = caso.radicais.length ? busca.correspondenciaExata(caso.texto) : null;
    assert.equal(exata?.id ?? null, caso.exata, "correspondência exata");
    assert.deepEqual(busca.correspondenciaPorNome(caso.texto).map((a) => a.id), caso.por_nome, "por nome");
    assert.equal(busca.nomeDeProduto(caso.texto), caso.nome_de_produto, "nome de produto");
    assert.deepEqual(
      busca.buscarCandidatos(caso.texto).map((c) => ({ id: c.atividade.id, pontuacao: c.pontuacao, termos: c.termos_casados })),
      caso.candidatos,
      "candidatos",
    );
  });
}

test("nome exato resolve sem LLM; frase livre devolve null", () => {
  assert.equal(busca.resolverSemLLM("Acompanhamento de metas").status, "encontrada");
  const saque = busca.resolverSemLLM("saque");
  assert.equal(saque.status, "ambigua");
  assert.ok(saque.alternativas.length >= 2);
  assert.equal(busca.resolverSemLLM("cliente pediu dinheiro para o negócio"), null);
  assert.equal(busca.resolverSemLLM("de da do"), null);
});

test("offline sem nome exato mostra candidatos com erro sem_internet", () => {
  const r = busca.resultadoOffline("cliente sacou dinheiro no caixa");
  assert.equal(r.status, "llm_indisponivel");
  assert.equal(r.erro.tipo, "sem_internet");
  assert.ok(r.candidatos.length > 0);
});

test("resultado local leva o motivo da falha", () => {
  assert.equal(busca.resultadoOffline("saque no caixa", "sessao_expirada").erro.tipo, "sessao_expirada");
});

test("erro de digitação no nome resolve no celular, com nota", () => {
  const r = busca.resolverSemLLM("acompanhamneto de metas");
  assert.equal(r.status, "encontrada");
  assert.equal(r.atividade.atividade, "Acompanhamento de metas");
  assert.match(r.justificativa, /entendido como "acompanhamento de metas"/);
});
