"""Utilitarios de texto compartilhados (reranking e avaliacao)."""
import re
import unicodedata

# Palavras muito comuns que nao dizem nada sobre o assunto do texto.
STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
    "das", "em", "no", "na", "nos", "nas", "por", "pelo", "pela", "para", "pra",
    "com", "sem", "e", "ou", "que", "se", "ao", "aos", "the", "is", "of", "and",
    "to", "in", "qual", "quais", "como", "quando", "onde", "porque",
    "sobre", "diz", "ser", "sao", "esta", "estao", "isso", "isto", "essa",
    "esse", "este", "esta", "mais", "muito", "entre", "seu", "sua", "seus",
    "suas", "ele", "ela", "eles", "elas", "ja", "nao", "sim", "tem", "ter",
    "foi", "era", "faz", "fazer", "pode", "deve", "quer", "cada", "outro",
    "outra", "mesmo", "mesma", "depois", "antes", "ainda", "tambem", "voce",
    "funciona", "significa", "explique", "fale", "serve",
}


def normalizar(texto: str) -> str:
    """Minusculas e sem acento: 'Consistência' -> 'consistencia'."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def palavras_chave(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9_]+", normalizar(texto))
            if len(p) > 2 and p not in STOPWORDS}
