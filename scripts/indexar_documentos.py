"""Envia os arquivos .txt de documentos/ para o servico de ingestao.

Cada paragrafo (bloco separado por linha em branco) vira um trecho, com o
nome do arquivo como origem. Os trechos vao para POST /indexar, que so
coloca na fila; o worker indexa em seguida.

Usa so a biblioteca padrao, entao roda sem instalar nada:

    python scripts/indexar_documentos.py                       # padrao
    python scripts/indexar_documentos.py --url http://localhost:8001 --pasta documentos

Pode rodar quantas vezes quiser: a ingestao ignora trechos ja indexados.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def ler_trechos(pasta: Path) -> list[dict]:
    trechos = []
    for arquivo in sorted(pasta.glob("*.txt")):
        texto = arquivo.read_text(encoding="utf-8")
        for paragrafo in texto.split("\n\n"):
            paragrafo = " ".join(paragrafo.split())
            if paragrafo:
                trechos.append({"texto": paragrafo, "origem": arquivo.name})
    return trechos


def esperar_servico(url: str, tentativas: int = 30):
    for _ in range(tentativas):
        try:
            with urllib.request.urlopen(f"{url}/saude", timeout=3):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    sys.exit(f"servico de ingestao nao respondeu em {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.getenv("URL_INGESTAO", "http://localhost:8001"))
    parser.add_argument("--pasta", default=str(Path(__file__).resolve().parent.parent / "documentos"))
    args = parser.parse_args()

    trechos = ler_trechos(Path(args.pasta))
    if not trechos:
        sys.exit(f"nenhum .txt encontrado em {args.pasta}")

    esperar_servico(args.url)
    requisicao = urllib.request.Request(
        f"{args.url}/indexar", method="POST",
        data=json.dumps(trechos, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(requisicao, timeout=10) as resposta:
            print(resposta.status, resposta.read().decode())
    except urllib.error.HTTPError as erro:
        sys.exit(f"ingestao respondeu {erro.code}: {erro.read().decode()}")

    origens = sorted({t["origem"] for t in trechos})
    print(f"{len(trechos)} trecho(s) de {len(origens)} arquivo(s) enviados para a fila:")
    for origem in origens:
        print("  -", origem)


if __name__ == "__main__":
    main()
