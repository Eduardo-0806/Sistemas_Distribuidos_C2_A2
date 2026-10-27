"""
Avaliacao automatica simples da resposta (extensao opcional).

Nao usa outro modelo: compara palavras-chave. Dois indicadores de 0 a 1:

  cobertura     -> quanto das palavras-chave da PERGUNTA aparece nos trechos
                   recuperados (a recuperacao achou algo sobre o assunto?)
  fundamentacao -> quanto das palavras-chave da RESPOSTA aparece nos trechos
                   (a resposta se apoia nos documentos ou "inventou"?)

E um criterio grosseiro, mas barato, deterministico e facil de explicar.
"""
from servicos.comum.texto import palavras_chave

# cabecalho do modo simulado (comum/llm.py), que nao vem dos documentos
_IGNORAR = {"modo", "simulado", "llm_api_key", "configurada", "pergunta",
            "base", "documentos", "recuperados", "txt"}


def _proporcao(parte: set, todo: set) -> float:
    if not parte:
        return 0.0
    return round(len(parte & todo) / len(parte), 2)


def avaliar(pergunta: str, resposta: str, trechos: list[str]) -> dict:
    contexto = palavras_chave(" ".join(trechos))
    fundamentacao = _proporcao(palavras_chave(resposta) - _IGNORAR, contexto)
    return {
        "cobertura": _proporcao(palavras_chave(pergunta), contexto),
        "fundamentacao": fundamentacao,
        "fundamentada": fundamentacao >= 0.5,
    }
