"""
Servico 2 - RECUPERACAO: dada uma pergunta, acha os trechos mais relevantes.

TAREFA 2: busca por similaridade do cosseno entre a pergunta e o indice.

Rodar: uvicorn servicos.recuperacao.app:app --port 8002
"""
import os

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from servicos.comum.embeddings import Vetorizador, similaridade

app = FastAPI(title="Recuperacao - C2.A2")
URL_INGESTAO = os.getenv("URL_INGESTAO", "http://localhost:8001")


class Consulta(BaseModel):
    pergunta: str = Field(min_length=1)
    top_k: int = Field(3, ge=1)


def obter_indice():
    """Busca o indice no servico de ingestao, traduzindo falhas de rede
    em erros HTTP claros para quem chamou."""
    try:
        r = requests.get(f"{URL_INGESTAO}/indice", timeout=10)
        r.raise_for_status()
    except (requests.ConnectionError, requests.Timeout):
        raise HTTPException(503, "servico de ingestao indisponivel")
    except requests.HTTPError:
        raise HTTPException(502, f"servico de ingestao respondeu {r.status_code}")
    return r.json()["itens"]


@app.post("/buscar")
def buscar(consulta: Consulta):
    """Devolve os top_k trechos mais parecidos com a pergunta."""
    itens = obter_indice()
    if not itens:
        return {"pergunta": consulta.pergunta, "resultados": []}

    # Os vetores do indice estao no vocabulario TF-IDF da ingestao. Ajustar
    # com os mesmos textos reproduz esse vocabulario (o TF-IDF e
    # deterministico), entao a pergunta cai no mesmo espaco vetorial.
    vetorizador = Vetorizador()
    vetorizador.ajustar([i["texto"] for i in itens])
    vetor_pergunta = vetorizador.vetorizar(consulta.pergunta)

    pontuados = [
        {"texto": i["texto"], "origem": i["origem"],
         "score": round(similaridade(vetor_pergunta, i["vetor"]), 4)}
        for i in itens
    ]
    # score 0 = nenhum termo em comum com a pergunta; nao serve de contexto
    relevantes = [p for p in pontuados if p["score"] > 0]
    relevantes.sort(key=lambda p: p["score"], reverse=True)

    return {"pergunta": consulta.pergunta,
            "resultados": relevantes[:consulta.top_k]}


@app.get("/saude")
def saude():
    return {"status": "ok"}
