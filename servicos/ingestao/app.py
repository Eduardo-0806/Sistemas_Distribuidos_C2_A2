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

from fastapi import FastAPI
from pydantic import BaseModel

from servicos.comum.embeddings import Vetorizador

app = FastAPI(title="Ingestao - C2.A2")

ARQUIVO_INDICE = Path(os.getenv("ARQUIVO_INDICE", "dados/indice.json"))

vetorizador = Vetorizador()
INDICE = []
# protege INDICE + arquivo contra requisicoes /indexar simultaneas
_trava = threading.Lock()


class Documento(BaseModel):
    texto: str
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


@app.post("/indexar")
def indexar(docs: list[Documento]):
    with _trava:
        for d in docs:
            INDICE.append({"texto": d.texto, "origem": d.origem})
        # reindexa tudo com o vocabulario novo
        _revetorizar()
        salvar_indice()
        return {"indexados": len(INDICE)}


@app.get("/indice")
def indice():
    """Consumido pelo servico de recuperacao."""
    return {"total": len(INDICE),
            "itens": [{"texto": i["texto"], "origem": i["origem"],
                       "vetor": i["vetor"]} for i in INDICE]}


@app.get("/saude")
def saude():
    return {"status": "ok", "documentos": len(INDICE),
            "arquivo_indice": str(ARQUIVO_INDICE)}
