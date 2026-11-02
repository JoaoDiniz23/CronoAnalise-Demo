# Cronoanálise em campo: chatbot de atividades + cronômetro (versão de demonstração)

**🔗 Teste a demo: [cronoanalise-demo.onrender.com](https://cronoanalise-demo.onrender.com)**
(abre direto, sem login; o primeiro acesso pode levar cerca de 1 minuto para carregar.
Na demo, o chat usa só a busca por palavras, sem IA.)

> **Esta é uma versão pública e anonimizada** de um app que desenvolvi para um
> projeto de consultoria (cronoanálise em agências de um grande banco). O código é
> o mesmo do app em produção. **Os dados do cliente foram retirados**, como explico
> na seção [O que não está aqui](#o-que-não-está-aqui-e-por-quê).

## O problema

Numa cronoanálise, consultores passam o dia nas agências observando funcionários
e registrando cada atividade numa folha de coleta: o que foi feito, para qual
produto, em quanto tempo. Cada registro precisa bater com um item da **base oficial
de atividades do cliente** (centenas de combinações atividade + produto) e com os
códigos da folha. Procurar o item certo numa tabela enorme, de pé e no meio do
atendimento, gerava erro e retrabalho.

## A solução

Um app mobile (PWA) usado pelos consultores no celular, com dois módulos:

- **Chatbot de atividades.** O consultor descreve o que viu com as próprias
  palavras ("cliente veio sacar dinheiro no caixa") e recebe o registro oficial
  correto, já com os códigos da folha.
  1. **Busca própria por palavras** (radicais, correção de digitação, pesos por
     raridade). Roda **no próprio celular e funciona offline**.
  2. **IA (LLM) só quando a busca não resolve**, recebendo o catálogo inteiro e
     regras de desambiguação.
  3. **Validação de toda resposta da IA contra a base.** Um ID fora do catálogo
     invalida a resposta, então **o app nunca inventa um código**. Quando há
     dúvida, devolve as opções em vez de chutar.
- **Cronômetro** baseado em timestamp, que continua certo com a tela bloqueada
  ou o app fechado.

Há também um **agente de IA revisor de folhas de coleta**: um prompt estruturado
com as regras de preenchimento, que revisa as folhas escaneadas e aponta erros
(`docs/agente-ia/`). As mesmas regras estão em código em `backend/folha/`.

**Resultado no projeto real:** usado em campo por **14 consultores**, testado com
**16 usuários simultâneos sem falhas**.

## O que não está aqui (e por quê)

Todo o material do cliente foi **removido ou substituído por dados fictícios**:

| No app real | Nesta versão |
|---|---|
| Base oficial de atividades do cliente (814 registros) | Base **fictícia e reduzida** de 139 atividades bancárias genéricas (`dados/atividades_padronizadas.json`) |
| Manual de coleta, molde oficial da folha e guia de atualização (PDFs) | **Removidos** |
| Legenda oficial da folha (segmentos de clientes, canais etc.) | Legenda **fictícia** com a mesma estrutura (`dados/legenda_folha_fisica.yaml`) |
| Lista real de agências visitadas | Lista de agências **fictícias** |
| Regras e definições específicas do cliente | Trocadas por equivalentes genéricas |
| Casos de teste escritos sobre a base real | Reescritos sobre a base fictícia |
| Histórico de desenvolvimento, planos e documentação interna | **Removidos** (este repositório começa sem histórico) |
| Nomes de consultores, folhas reais escaneadas, chaves de API | Nunca estiveram aqui |

Por isso, os números de avaliação desta versão (recall da busca, casos de teste)
**não são os do projeto real**: servem só para mostrar como o sistema funciona.

## Como rodar

```
python -m venv venv
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Copie `.env.exemplo` para `.env` e preencha ao menos `ACESSO_SENHA` e
`ANTHROPIC_API_KEY`. Sem a chave, o chat funciona só com a busca por palavras.
Para testar em `http://localhost`, use `ACESSO_COOKIE_INSEGURO=1`.

## Testes

- Python (330 testes): `venv\Scripts\python -m pytest`
- Frontend (135 testes): `npm test` (test runner nativo do Node, sem dependências)
- Avaliação da busca: `python scripts/avaliar_busca.py` (com `--llm` usa a IA e gasta crédito)
- Paridade Python × JavaScript: a busca offline do celular (`frontend/busca-local.js`)
  é uma cópia da busca do servidor, e `tests/dados_busca/paridade_busca.json`
  garante que as duas respondem igual.

## Estrutura

- `backend/main.py`: FastAPI com login, `/health`, `POST /api/atividades/buscar`,
  `GET /api/atividades` (base para a busca offline) e o frontend estático.
- `backend/acesso.py`: senha, cookie de sessão e limites de uso (controle de custo da IA).
- `backend/busca/`: busca de atividades (palavras → IA → validação).
- `backend/dados/`: única porta de entrada para a base; valida tudo na carga.
- `backend/folha/`: regras da folha de coleta, também usadas como referência do agente revisor.
- `frontend/`: PWA em HTML/CSS/JS puro, sem build. `sw.js` faz o app abrir offline.
- `dados/`: base e legenda **fictícias**.
- `scripts/`: avaliação da busca, paridade Python/JS e verificação da base.
- `docs/agente-ia/`: prompt do agente revisor de folhas.

## Stack

Python · FastAPI · Pydantic · Claude API · JavaScript (PWA, Service Worker) ·
Docker (deploy no Render) · pytest / node:test

Desenvolvido por **João Diniz Borges** com Claude Code.
