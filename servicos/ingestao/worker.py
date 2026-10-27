"""Consome documentos do Redis e solicita sua indexacao ao servico de ingestao.

Fila confiavel (padrao "reliable queue" do Redis):

  ingestao:documentos    fila principal (o endpoint /indexar faz RPUSH aqui)
  ingestao:processando   mensagem que o worker pegou e ainda esta tratando
  ingestao:falhas        "dead letter": mensagens que nunca vao dar certo

  1. BLMOVE tira a mensagem da fila principal e a coloca em "processando"
     numa operacao atomica. Se o worker morrer no meio, a mensagem NAO se
     perde: ela continua em "processando" e volta para a fila quando o
     worker reinicia.
  2. Deu certo -> remove de "processando".
  3. Falha transitoria (ingestao fora do ar, tempo-limite, 5xx) -> devolve
     para o fim da fila e tenta de novo depois.
  4. Falha permanente (JSON invalido, 4xx) -> manda para "ingestao:falhas".

Isso da entrega "pelo menos uma vez"; duplicatas sao toleradas porque a
ingestao e idempotente (ignora documento ja indexado).

Rodar: python -m servicos.ingestao.worker
"""
import json
import logging
import os
import time

import redis
import requests

URL_INGESTAO = os.getenv("URL_INGESTAO", "http://localhost:8001")
FILA_INGESTAO = "ingestao:documentos"
FILA_PROCESSANDO = "ingestao:processando"
FILA_FALHAS = "ingestao:falhas"
ESPERA_REENVIO = float(os.getenv("WORKER_ESPERA_REENVIO", "2"))

log = logging.getLogger("worker")


class FalhaPermanente(Exception):
    """A mensagem nunca vai ser aceita; nao adianta tentar de novo."""


def processar_mensagem(mensagem):
    try:
        documentos = json.loads(mensagem)
    except ValueError as erro:
        raise FalhaPermanente(f"JSON invalido: {erro}") from erro
    resposta = requests.post(f"{URL_INGESTAO}/indexar/processar",
                             json=documentos, timeout=(3, 60))
    if 400 <= resposta.status_code < 500:
        raise FalhaPermanente(f"ingestao recusou ({resposta.status_code}): "
                              f"{resposta.text[:200]}")
    resposta.raise_for_status()
    return resposta.json()


def recuperar_pendentes(fila):
    """Devolve para a fila o que ficou em 'processando' (worker caiu no meio)."""
    recuperadas = 0
    while fila.lmove(FILA_PROCESSANDO, FILA_INGESTAO, "RIGHT", "LEFT"):
        recuperadas += 1
    if recuperadas:
        log.warning("%d mensagem(ns) pendente(s) devolvida(s) para a fila", recuperadas)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    fila = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                                socket_connect_timeout=3)
    recuperar_pendentes(fila)
    log.info("Aguardando documentos na fila %s", FILA_INGESTAO)
    while True:
        try:
            mensagem = fila.blmove(FILA_INGESTAO, FILA_PROCESSANDO, 5, "LEFT", "RIGHT")
        except redis.RedisError:
            log.exception("Redis indisponivel; nova tentativa em 5s")
            time.sleep(5)
            continue
        if mensagem is None:
            continue

        try:
            resultado = processar_mensagem(mensagem)
            fila.lrem(FILA_PROCESSANDO, 1, mensagem)
            log.info("Documentos processados: %s", resultado)
        except FalhaPermanente as erro:
            log.error("Mensagem descartada para %s: %s", FILA_FALHAS, erro)
            with fila.pipeline() as tx:  # MULTI/EXEC: as duas operacoes juntas
                tx.lrem(FILA_PROCESSANDO, 1, mensagem)
                tx.rpush(FILA_FALHAS, mensagem)
                tx.execute()
        except requests.RequestException as erro:
            log.warning("Falha transitoria (%s); mensagem volta para a fila em %.0fs",
                        type(erro).__name__, ESPERA_REENVIO)
            time.sleep(ESPERA_REENVIO)
            with fila.pipeline() as tx:
                tx.lrem(FILA_PROCESSANDO, 1, mensagem)
                tx.rpush(FILA_INGESTAO, mensagem)
                tx.execute()


if __name__ == "__main__":
    main()
