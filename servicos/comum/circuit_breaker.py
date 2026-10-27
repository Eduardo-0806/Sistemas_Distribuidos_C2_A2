"""
Circuit breaker (disjuntor) - baseado no modelo de referencia da Aula 11.

Estados:
  fechado  -> deixa passar (normal)
  aberto   -> recusa na hora, sem tentar (servico esta quebrado)
  meio     -> deixa passar UMA chamada de teste para ver se voltou

Adaptacao feita pelo grupo: o FastAPI executa endpoints sincronos em um
pool de threads, entao varias requisicoes podem usar o mesmo disjuntor ao
mesmo tempo. Por isso as transicoes de estado sao protegidas por uma trava,
e no estado "meio" so UMA chamada de teste passa; as demais sao recusadas
ate o teste terminar.
"""
import threading
import time


class CircuitoAberto(Exception):
    """Levantada quando o disjuntor esta aberto e recusa a chamada."""


class CircuitBreaker:

    def __init__(self, limite_falhas=5, espera_segundos=30, nome="disjuntor"):
        self.nome = nome
        self.limite_falhas = limite_falhas
        self.espera_segundos = espera_segundos
        self.falhas = 0
        self.estado = "fechado"
        self.aberto_em = 0.0
        self._trava = threading.Lock()
        self._teste_em_andamento = False

    def chamar(self, funcao, *args, **kwargs):
        self._antes_da_chamada()
        try:
            resultado = funcao(*args, **kwargs)
        except Exception:
            self._registrar_falha()
            raise
        self._registrar_sucesso()
        return resultado

    def _antes_da_chamada(self):
        with self._trava:
            if self.estado == "aberto":
                if time.time() - self.aberto_em >= self.espera_segundos:
                    self.estado = "meio"
                else:
                    raise CircuitoAberto(f"{self.nome} aberto: chamada recusada")
            if self.estado == "meio":
                if self._teste_em_andamento:
                    raise CircuitoAberto(f"{self.nome} em teste: chamada recusada")
                self._teste_em_andamento = True

    def _registrar_falha(self):
        with self._trava:
            self.falhas += 1
            if self.falhas >= self.limite_falhas or self.estado == "meio":
                self.estado = "aberto"
                self.aberto_em = time.time()
            self._teste_em_andamento = False

    def _registrar_sucesso(self):
        with self._trava:
            self.falhas = 0
            self.estado = "fechado"
            self._teste_em_andamento = False

    def situacao(self):
        """Resumo para o endpoint /saude."""
        with self._trava:
            restante = 0.0
            if self.estado == "aberto":
                restante = max(0.0, self.espera_segundos
                               - (time.time() - self.aberto_em))
            return {"estado": self.estado, "falhas": self.falhas,
                    "limite_falhas": self.limite_falhas,
                    "reabre_teste_em_s": round(restante, 1)}
