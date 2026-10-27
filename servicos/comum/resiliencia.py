"""
Retentativa com recuo exponencial (exponential backoff) para chamadas remotas.

Usada pelo servico de geracao em conjunto com o circuit breaker:

    disjuntor.chamar(com_retentativa, gerar, pergunta, contexto)

Ou seja, a retentativa fica DENTRO do disjuntor: uma requisicao do usuario
faz ate N tentativas; se todas falharem, o disjuntor conta UMA falha.
Quando o disjuntor abre, nem a primeira tentativa e feita (falha rapida).

So vale a pena tentar de novo quando a falha e TRANSITORIA (rede caiu,
tempo-limite estourou, servidor 5xx, limite de taxa 429). Erros como
401 (chave invalida) ou 400 (requisicao errada) nao melhoram tentando de
novo, entao sao repassados na hora.
"""
import logging
import random
import time

import requests

log = logging.getLogger(__name__)

STATUS_TRANSITORIOS = {408, 425, 429, 500, 502, 503, 504}


def falha_transitoria(erro: Exception) -> bool:
    if isinstance(erro, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(erro, requests.HTTPError) and erro.response is not None:
        return erro.response.status_code in STATUS_TRANSITORIOS
    return False


def com_retentativa(funcao, *args, tentativas=3, espera_inicial=0.5,
                    espera_maxima=4.0, **kwargs):
    """Executa funcao(*args, **kwargs) com ate `tentativas` tentativas.

    Entre uma tentativa e outra espera espera_inicial * 2^n segundos
    (limitado a espera_maxima), com um pequeno jitter aleatorio para que
    varias instancias nao martelem a API ao mesmo tempo.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            return funcao(*args, **kwargs)
        except Exception as erro:
            if tentativa == tentativas or not falha_transitoria(erro):
                raise
            espera = min(espera_maxima, espera_inicial * 2 ** (tentativa - 1))
            espera += random.uniform(0, espera * 0.1)
            log.warning("tentativa %d/%d falhou (%s); nova tentativa em %.2fs",
                        tentativa, tentativas, type(erro).__name__, espera)
            time.sleep(espera)
