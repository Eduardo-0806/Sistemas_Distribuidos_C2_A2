"""
Servico 1 - INGESTAO: recebe documentos, gera embeddings e armazena.

TAREFA 1: o indice e persistido em disco (arquivo JSON) e recarregado
ao iniciar, entao nao se perde quando o servico reinicia.

Rodar: uvicorn servicos.ingestao.app:app --port 8001
"""
import json
import os
import threading
from pathlib import Path

import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from servicos.comum.embeddings import Vetorizador

app = FastAPI(title="Ingestao - C2.A2")

ARQUIVO_INDICE = Path(os.getenv("ARQUIVO_INDICE", "dados/indice.json"))
fila = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                            socket_connect_timeout=3, socket_timeout=3)
FILA_INGESTAO = "ingestao:documentos"

vetorizador = Vetorizador()
INDICE = []
# protege INDICE + arquivo contra requisicoes /indexar simultaneas
_trava = threading.Lock()


class Documento(BaseModel):
    texto: str = Field(min_length=1)
    origem: str = "desconhecida"


def _revetorizar():
    """Reajusta o vocabulario com todos os textos e recalcula os vetores."""
    if not INDICE:
        return
    vetorizador.ajustar([i["texto"] for i in INDICE])
    for item in INDICE:
        item["vetor"] = vetorizador.vetorizar(item["texto"])


def salvar_indice():
    """Grava o indice de forma atomica: escreve num temporario e renomeia,
    assim uma queda no meio da escrita nao corrompe o arquivo anterior."""
    ARQUIVO_INDICE.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO_INDICE.with_suffix(".tmp")
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(INDICE, f, ensure_ascii=False)
    os.replace(temporario, ARQUIVO_INDICE)


def carregar_indice():
    """Recarrega o indice do disco (se existir) e reajusta o vetorizador,
    para que novas indexacoes usem o mesmo vocabulario."""
    if not ARQUIVO_INDICE.exists():
        return
    with open(ARQUIVO_INDICE, encoding="utf-8") as f:
        INDICE.extend(json.load(f))
    _revetorizar()


carregar_indice()


@app.post("/indexar", status_code=202)
def indexar(docs: list[Documento]):
    """Enfileira documentos para processamento pelo worker (assincrono:
    responde 202 Accepted na hora, a indexacao acontece depois)."""
    if not docs:
        raise HTTPException(422, "envie ao menos um documento")
    mensagem = json.dumps([d.model_dump() for d in docs], ensure_ascii=False)
    try:
        fila.rpush(FILA_INGESTAO, mensagem)
    except redis.RedisError:
        raise HTTPException(503, "fila de ingestao indisponivel")
    return {"enfileirados": len(docs)}


@app.post("/indexar/processar", include_in_schema=False)
def processar(docs: list[Documento]):
    """Chamado pelo worker; mantem o indice sob responsabilidade da ingestao.

    Idempotente: a fila entrega "pelo menos uma vez" (o worker reenfileira
    em caso de falha), entao a mesma mensagem pode chegar duas vezes.
    Um documento com a mesma origem e o mesmo texto de outro ja indexado
    e ignorado, e o indice nao fica com duplicatas."""
    with _trava:
        existentes = {(i["origem"], i["texto"]) for i in INDICE}
        novos = 0
        for d in docs:
            chave = (d.origem, d.texto)
            if chave in existentes:
                continue
            INDICE.append({"texto": d.texto, "origem": d.origem})
            existentes.add(chave)
            novos += 1
        if novos:
            # reindexa tudo com o vocabulario novo
            _revetorizar()
            salvar_indice()
        return {"novos": novos, "ignorados": len(docs) - novos,
                "indexados": len(INDICE)}


@app.get("/indice")
def indice():
    """Consumido pelo servico de recuperacao."""
    return {"total": len(INDICE),
            "itens": [{"texto": i["texto"], "origem": i["origem"],
                       "vetor": i["vetor"]} for i in INDICE]}


@app.get("/saude")
def saude():
    try:
        pendentes = fila.llen(FILA_INGESTAO)
    except redis.RedisError:
        pendentes = None  # fila fora do ar nao derruba a ingestao
    return {"status": "ok", "documentos": len(INDICE),
            "fila_pendentes": pendentes,
            "arquivo_indice": str(ARQUIVO_INDICE)}
