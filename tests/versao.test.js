/**
 * `?v=` do index.html, os imports entre módulos e VERSAO do sw.js precisam
 * andar juntos: versão desencontrada faz o service worker guardar um
 * arquivo que a página nunca pede — e o app não abre offline.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const frontend = new URL("../frontend/", import.meta.url);
const ler = (nome) => readFileSync(new URL(nome, frontend), "utf-8");

test("uma única versão em index.html, imports e sw.js", () => {
  const versaoSw = ler("sw.js").match(/const VERSAO = "([^"]+)"/)[1];
  const usadas = new Set();
  for (const nome of readdirSync(frontend).filter((n) => /\.(html|js)$/.test(n) && n !== "sw.js")) {
    for (const [, v] of ler(nome).matchAll(/\?v=([\w-]+)/g)) usadas.add(v);
  }
  assert.deepEqual([...usadas], [versaoSw]);
});

test("todo script/estilo do index.html está na lista do service worker", () => {
  const sw = ler("sw.js");
  for (const [, arquivo] of ler("index.html").matchAll(/(?:src|href)="([\w-]+\.(?:js|css))\?v=/g)) {
    assert.ok(sw.includes(`/${arquivo}?v=\${VERSAO}`), `${arquivo} fora do sw.js`);
  }
  for (const nome of ["app.js", "chat-app.js"]) {
    for (const [, arquivo] of ler(nome).matchAll(/from "\.\/([\w-]+\.js)\?v=/g)) {
      assert.ok(sw.includes(`/${arquivo}?v=\${VERSAO}`), `${arquivo} (import de ${nome}) fora do sw.js`);
    }
  }
});
