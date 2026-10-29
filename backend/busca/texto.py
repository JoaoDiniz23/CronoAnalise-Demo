"""
Normalização de texto para a busca de atividades.

Porte para Python do motor determinístico do protótipo
`conteúdos importantes/Chatbot.html` (funções `norm`, `stem` e a lista
STOPWORDS). Mantido propositalmente simples: minúsculas, sem acento,
stemming leve por lista de sufixos. Nada aqui altera o dado oficial — a
normalização é aplicada só a cópias usadas para comparar texto.
"""

import re
import unicodedata

# Sufixos do protótipo, testados do maior para o menor. Acrescentados
# aqui: passado dos verbos ("pagou", "transferiu" — é assim que o consultor
# relata o que viu) e "-ência/-ância", para o verbo casar com o substantivo
# da base ("transferiu" x "transferência", "pagou" x "pagamento").
_SUFIXOS = sorted(
    [
        "acoes", "acao", "amento", "imento", "mente", "ando", "endo", "indo",
        "aria", "eria", "iria", "adora", "adoras", "adores", "ador", "ante",
        "adas", "ados", "idas", "idos", "ada", "ado", "ida", "ido",
        "coes", "cao", "ar", "er", "ir",
        # acrescentados
        "aram", "eram", "iram", "avam", "ava", "ou", "eu", "iu",
        "encia", "ancia",
    ],
    key=len,
    reverse=True,
)

# Stopwords do protótipo, mais alguns verbos/palavras de relato que o
# consultor usa ao descrever uma observação ("atendeu o cliente para...")
# e que não distinguem uma atividade de outra.
STOPWORDS = frozenset(
    {
        # do protótipo
        "estou", "fazendo", "fazer", "faco", "quero", "queria", "preciso",
        "gostaria", "sobre", "como", "qual", "quais", "um", "uma", "uns",
        "umas", "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as",
        "para", "pra", "por", "no", "na", "nos", "nas", "em", "com", "que",
        "meu", "minha", "ao", "aos", "sou", "esse", "essa", "este", "esta",
        "isso", "ele", "ela", "eu", "se", "ja", "la", "aqui", "tem", "ter",
        "me", "ver",
        # relato de observação em campo
        "consultor", "consultora", "gerente", "funcionario", "funcionaria",
        "estava", "esteve", "foi", "era", "seu", "sua", "seus", "suas",
        "dele", "dela", "lhe", "pelo", "pela", "pelos", "pelas", "num",
        "numa", "muito", "pouco", "mais", "menos", "tambem", "entao",
        "depois", "antes", "durante", "quando", "onde", "ali", "algum",
        "alguma", "outro", "outra", "ou",
        # verbos de relato (28/09): só dizem que houve conversa, nunca qual
        # atividade. Nenhum é nome de atividade/produto da base (teste).
        # Ficam de fora os que mudam a atividade: perguntar/explicar
        # (dúvida), atender, ajudar, orientar, informar, contar, mostrar.
        "fala", "falar", "falando", "falou", "conversa", "conversar",
        "conversando", "conversou", "comentar", "comentando", "comentou",
        "dizer", "dizendo", "disse",
        # tempo (29/09): hora e circunstância não são a atividade. "No
        # início do dia" fazia "Abertura do sistema no início da jornada"
        # passar à frente de "Abertura e fechamento da loja" (único nome da
        # base com essas palavras; continua achado por "abertura do sistema").
        "inicio", "fim", "dia", "dias", "manha", "tarde", "noite", "jornada",
        "expediente", "hoje", "ontem", "cedo",
    }
)

_NAO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos (equivalente ao `norm` do protótipo)."""
    decomposto = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def radical(palavra: str) -> str:
    """Stemming leve PT-BR (equivalente ao `stem` do protótipo)."""
    s = palavra[:-1] if palavra.endswith("s") else palavra
    for sufixo in _SUFIXOS:
        if s.endswith(sufixo) and len(s) - len(sufixo) >= 3:
            return s[: -len(sufixo)]
    return s


# Palavra do relato → como a base escreve. Ordinal por extenso ("2ª via"
# vira "2" sem a pontuação), verbos cujo radical não casa com o
# substantivo da base ("sac" x "saqu" de "Saque"; "abr" x "abertura") e
# "agência", que o cliente chama de "loja". Vale dos dois lados (relato
# e base), então nome oficial com essas palavras continua achado.
_EQUIVALENTES = {
    "segunda": "2", "2a": "2", "2o": "2",
    "saca": "saque", "sacar": "saque", "sacou": "saque", "sacando": "saque",
    "sacaram": "saque", "sacado": "saque",
    **dict.fromkeys(
        ["abrir", "abre", "abrem", "abriu", "abriram", "abrindo", "abria", "abriam",
         "aberto", "aberta", "abertos", "abertas"],
        "abertura",
    ),
    "agencia": "loja", "agencias": "loja",
}


def palavras(texto: str) -> list[str]:
    """Palavras normalizadas, sem pontuação."""
    return [
        _EQUIVALENTES.get(p, p) for p in _NAO_ALFANUMERICO.split(normalizar(texto)) if p
    ]


def radicais(texto: str) -> list[str]:
    """Radicais das palavras relevantes (sem stopwords e sem letras soltas —
    dígito solto fica, pelo "2ª via"), na ordem em que aparecem, sem repetição."""
    vistos: dict[str, None] = {}
    for p in palavras(texto):
        if (len(p) < 2 and not p.isdigit()) or p in STOPWORDS:
            continue
        vistos.setdefault(radical(p), None)
    return list(vistos)


# ------------------------------------------------------------------------
# Correção de erro de digitação (23/09/2026)
#
# Palavra que não existe no vocabulário da base é trocada pela palavra da
# base mais parecida — mas só quando a candidata é ÚNICA e bem próxima:
#   - até 4 letras: nunca corrige ("copa" virava "fopa");
#   - palavra cuja raiz a busca já reconhece não é corrigida ("cadastrou",
#     "vendi" são flexões, não erros);
#   - no máximo 1 edição, em qualquer tamanho (com 2, "banheiro" virava
#     "dinheiro");
#   - edição = letra trocada, faltando, sobrando ou duas vizinhas invertidas.
# Empate entre candidatas → não corrige (o LLM decide). Só vale para a
# parte determinística da busca; o LLM recebe o texto original.
# Cópia fiel em frontend/busca-local.js (paridade testada).
# ------------------------------------------------------------------------


def distancia_edicao(a: str, b: str, limite: int) -> int:
    """Distância de Damerau-Levenshtein restrita (transposição de vizinhas).
    Devolve `limite + 1` assim que passar do limite."""
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    anterior2: list[int] = []
    anterior = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        atual = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            custo = 0 if a[i - 1] == b[j - 1] else 1
            atual[j] = min(anterior[j] + 1, atual[j - 1] + 1, anterior[j - 1] + custo)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                atual[j] = min(atual[j], anterior2[j - 2] + 1)
        if min(atual) > limite:
            return limite + 1
        anterior2, anterior = anterior, atual
    return anterior[len(b)]


class CorretorDigitacao:
    def __init__(self, textos_da_base):
        self.vocabulario = frozenset(p for t in textos_da_base for p in palavras(t))
        self.raizes = frozenset(radical(p) for p in self.vocabulario)

    def _corrigir_palavra(self, p: str) -> str:
        if p in self.vocabulario or len(p) <= 4 or p in STOPWORDS or p.isdigit():
            return p
        rp = radical(p)
        # Flexão de palavra conhecida: a raiz digitada é o começo de uma
        # raiz da base ("cadastrou" → "cadastr" ⊂ "cadastro"). O contrário
        # não vale: "acompanhamneto" começa com "acompanh", mas é erro.
        if len(rp) >= 4 and any(r.startswith(rp) for r in self.raizes):
            return p
        limite = 1
        melhor, empatadas = limite + 1, []
        for v in self.vocabulario:
            d = distancia_edicao(p, v, limite)
            if d < melhor:
                melhor, empatadas = d, [v]
            elif d == melhor and d <= limite:
                empatadas.append(v)
        return empatadas[0] if melhor <= limite and len(empatadas) == 1 else p

    def corrigir(self, texto: str) -> str:
        return " ".join(self._corrigir_palavra(p) for p in palavras(texto))
