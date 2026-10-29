/**
 * Códigos da folha física mostrados no cartão do chat (`frontend/legenda.js`).
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  atendimentoDaFolha,
  classificacaoDaFolha,
  clientesDaFolha,
  segmentoDaFolha,
  produtoDaFolha,
  valoresSemCodigo,
} from "../frontend/legenda.js";

test("classificação vem com o código da folha", () => {
  assert.equal(classificacaoDaFolha("Gestão de equipe + TNP"), "19 – TNP: Gestão de Equipe");
  assert.equal(classificacaoDaFolha("Pós venda + Comercial"), "3 – C: Pós Venda");
  assert.equal(classificacaoDaFolha("Treinamento + Comercial"), "8 – C: Treinamento");
});

test("classificação desconhecida devolve null (a tela mostra o texto original)", () => {
  assert.equal(classificacaoDaFolha("Algo novo + Comercial"), null);
});

test("campos multivalor ganham código e preservam valor desconhecido", () => {
  assert.equal(clientesDaFolha(["Pessoa Fisica", "Pessoa Jurídica"]), "1 – Cliente PF, 2 – Cliente PJ");
  assert.equal(segmentoDaFolha(["Alta Renda", "MEI", "Novo"]), "AR – Alta Renda, MEI, Novo");
  assert.equal(atendimentoDaFolha(["Outros", "Presencial"]), "4 – Outro, 5 – Presencial");
});

test("todo valor da base de atividades tem código da folha", () => {
  const base = JSON.parse(
    readFileSync(new URL("../dados/atividades_padronizadas.json", import.meta.url), "utf-8"),
  );
  const faltando = new Set(base.flatMap(valoresSemCodigo));
  assert.deepEqual([...faltando], []);
});

test("produto aparece como vai escrito na folha, sem parêntese", () => {
  assert.equal(produtoDaFolha("Capital de Giro (Empréstimo)"), "Capital de Giro");
  assert.equal(produtoDaFolha("Recebimento de Títulos (Boleto)"), "Recebimento de Títulos");
  assert.equal(produtoDaFolha("Numerário (Dinheiro)"), "Numerário");
  assert.equal(produtoDaFolha("Conta Corrente"), "Conta Corrente");
});

test("nenhum produto da base fica com parêntese ou vazio na tela", () => {
  const base = JSON.parse(
    readFileSync(new URL("../dados/atividades_padronizadas.json", import.meta.url), "utf-8"),
  );
  for (const produto of new Set(base.map((a) => a.produto))) {
    const naFolha = produtoDaFolha(produto);
    assert.ok(naFolha && !naFolha.includes("("), `${produto} → ${naFolha}`);
  }
});
