"""Consome documentos do Redis e solicita sua indexacao ao servico de ingestao.

Rodar: python -m servicos.ingestao.worker
"""
import json
import logging
import os

import redis
import requests

URL_INGESTAO = os.getenv("URL_INGESTAO", "http://localhost:8001")
FILA_INGESTAO = "ingestao:documentos"


def processar_mensagem(mensagem):
    resposta = requests.post(
        f"{URL_INGESTAO}/indexar/processar",
        json=json.loads(mensagem),
        timeout=60,
    )
    resposta.raise_for_status()


def main():
    logging.basicConfig(level=logging.INFO)
    fila = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    logging.info("Aguardando documentos na fila %s", FILA_INGESTAO)
    while True:
        item = fila.blpop(FILA_INGESTAO, timeout=5)
        if item is None:
            continue
        try:
            processar_mensagem(item[1])
            logging.info("Documentos indexados")
        except (ValueError, requests.RequestException):
            logging.exception("Falha ao processar documentos da fila")


if __name__ == "__main__":
    main()
