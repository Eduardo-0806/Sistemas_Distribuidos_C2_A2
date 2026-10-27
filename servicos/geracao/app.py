"""
Servico 3 - GERACAO: monta o prompt com o contexto e chama o LLM.

Fluxo de /perguntar:
  1. pede os trechos relevantes ao servico de RECUPERACAO (REST);
  2. chama o LLM com a pergunta + trechos;
  3. devolve a resposta, as fontes citadas e uma avaliacao simples.

Resiliencia:
  - chamada ao LLM: tempo-limite (LLM_TIMEOUT, em comum/llm.py)
    + retentativa com recuo exponencial (comum/resiliencia.py)
    + circuit breaker (comum/circuit_breaker.py);
  - chamada a recuperacao: tempo-limite + circuit breaker proprio;
  - degradacao elegante: se o LLM estiver fora, responde 503 mas ainda
    entrega os trechos recuperados, para o usuario nao ficar sem nada.

Rodar: uvicorn servicos.geracao.app:app --port 8003
"""
import logging
import os

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from servicos.comum.circuit_breaker import CircuitBreaker, CircuitoAberto
from servicos.comum.llm import gerar
from servicos.comum.resiliencia import com_retentativa
from servicos.geracao.avaliacao import avaliar

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("geracao")

app = FastAPI(title="Geracao - C2.A2")
URL_RECUPERACAO = os.getenv("URL_RECUPERACAO", "http://localhost:8002")
TIMEOUT_RECUPERACAO = float(os.getenv("TIMEOUT_RECUPERACAO", "10"))
LLM_TENTATIVAS = int(os.getenv("LLM_TENTATIVAS", "3"))
TOP_K = int(os.getenv("TOP_K", "3"))

# Um disjuntor por dependencia: se a recuperacao cair, isso nao "contamina"
# o estado do disjuntor do LLM (e vice-versa).
disjuntor = CircuitBreaker(
    limite_falhas=int(os.getenv("LLM_LIMITE_FALHAS", "3")),
    espera_segundos=float(os.getenv("LLM_ESPERA_SEGUNDOS", "20")),
    nome="disjuntor do LLM")
disjuntor_recuperacao = CircuitBreaker(limite_falhas=3, espera_segundos=10,
                                       nome="disjuntor da recuperacao")

SEM_CONTEXTO = ("Nao encontrei nos documentos indexados nenhum trecho "
                "relacionado a essa pergunta, entao nao posso responder com base neles.")


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1)
    top_k: int = Field(TOP_K, ge=1, le=10)


def _chamar_recuperacao(pergunta: str, top_k: int) -> requests.Response:
    r = requests.post(f"{URL_RECUPERACAO}/buscar",
                      json={"pergunta": pergunta, "top_k": top_k},
                      timeout=(3, TIMEOUT_RECUPERACAO))
    if r.status_code >= 500:
        # 5xx (ex.: a ingestao caiu) conta como falha no disjuntor;
        # 4xx e erro de quem chamou, entao nao conta.
        r.raise_for_status()
    return r


def buscar_trechos(pergunta: str, top_k: int) -> list[dict]:
    try:
        r = disjuntor_recuperacao.chamar(_chamar_recuperacao, pergunta, top_k)
        if r.status_code >= 400:
            raise HTTPException(502, f"recuperacao respondeu {r.status_code}: {r.text}")
        return r.json()["resultados"]
    except CircuitoAberto:
        raise HTTPException(503, "servico de recuperacao indisponivel "
                                 "(disjuntor aberto): tente novamente mais tarde")
    except (requests.ConnectionError, requests.Timeout):
        raise HTTPException(503, "servico de recuperacao indisponivel")
    except requests.HTTPError as erro:
        raise HTTPException(502, f"recuperacao falhou: {erro.response.status_code}")


def _fontes(trechos: list[dict]) -> list[str]:
    """Documentos que embasaram a resposta, sem repeticao, em ordem de relevancia."""
    return list(dict.fromkeys(t["origem"] for t in trechos))


def _degradado(pergunta: str, trechos: list[dict], motivo: str) -> JSONResponse:
    """Resposta quando o LLM nao pode ser usado: 503, mas com os trechos."""
    return JSONResponse(status_code=503, content={
        "pergunta": pergunta,
        "resposta": None,
        "erro": motivo,
        "modo": "degradado",
        "mensagem": "O gerador de respostas esta indisponivel. Seguem os trechos "
                    "dos documentos mais relacionados a sua pergunta.",
        "fontes": _fontes(trechos),
        "trechos": trechos,
        "disjuntor": disjuntor.estado,
    })


@app.post("/perguntar")
def perguntar(p: Pergunta):
    trechos = buscar_trechos(p.pergunta, p.top_k)

    if not trechos:
        # sem contexto nao faz sentido gastar uma chamada ao LLM
        return {"pergunta": p.pergunta, "resposta": SEM_CONTEXTO, "modo": "sem_contexto",
                "fontes": [], "trechos": [], "avaliacao": None}

    contexto = [f"[{t['origem']}] {t['texto']}" for t in trechos]
    try:
        resposta = disjuntor.chamar(com_retentativa, gerar, p.pergunta, contexto,
                                    tentativas=LLM_TENTATIVAS)
    except CircuitoAberto:
        log.warning("disjuntor do LLM aberto: chamada recusada sem tentar")
        return _degradado(p.pergunta, trechos,
                          "circuito do LLM aberto: tente novamente mais tarde")
    except Exception as erro:
        log.error("LLM falhou apos %d tentativas: %r", LLM_TENTATIVAS, erro)
        return _degradado(p.pergunta, trechos,
                          f"LLM indisponivel ({type(erro).__name__})")

    return {
        "pergunta": p.pergunta,
        "resposta": resposta,
        "modo": "simulado" if resposta.startswith("[MODO SIMULADO") else "llm",
        "fontes": _fontes(trechos),
        "trechos": trechos,
        "avaliacao": avaliar(p.pergunta, resposta, [t["texto"] for t in trechos]),
    }


@app.get("/saude")
def saude():
    return {"status": "ok",
            "disjuntor": disjuntor.estado,
            "disjuntores": {"llm": disjuntor.situacao(),
                            "recuperacao": disjuntor_recuperacao.situacao()}}
