"""O jogo aguenta o ciclo de render nas duas ramificações do ecrã de espera.

    ../.venv/bin/python test_game_smoke.py        (a partir de game/)

PRECISA DE ECRÃ. Abre a janela do jogo durante uns 20 segundos e fecha-a. Não
serve para correr numa máquina sem display; é para correr antes de um evento,
na máquina do evento.

Porque isto existe, e porque não podia ser um teste de unidade: o ciclo de
render vive todo dentro de `Game.run()`. Uma alteração deixou lá um nome que
já não existia (`desde_o_arranque`), e isso rebentava com `NameError` no
instante em que o jogo saísse do ecrã de espera — ou seja, mal o QR
aparecesse, em todos os eventos. Nenhum dos testes de unidade lhe tocou, e eu
tinha corrido o jogo ANTES dessa alteração, não depois. Foi apanhado numa
revisão, não por mim.

O que se prova aqui é simples e é o que faltava: o jogo arranca sem QR, sobrevive
ao QR aparecer, e sobrevive ao QR desaparecer. As três coisas passam pelos dois
caminhos do `if a_preparar:` e por toda a pintura que vem a seguir.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
VENV_PY = REPO / ".venv" / "bin" / "python3"
QR = AQUI / "resources" / "images" / "qr_lobby.png"
ASSETS = os.environ.get("HUGO_ASSETS", str(Path.home() / "Claude code/hugo-assets/gold/BigFile"))


class RespondedorDeAudio:
    """Responde de imediato nas portas de áudio do jogo, como o bridge faz.

    Sem isto o teste não mede nada: `game/audio_helper.py` faz `settimeout(1.0)`
    e espera resposta no fio principal, portanto sem ninguém a atender cada
    frame leva mais de oito segundos e o jogo nem chega a desenhar o primeiro.
    Foi assim que uma primeira versão deste teste deu tudo por bom sem o jogo
    ter pintado coisa nenhuma.
    """

    PORTAS = (9001, 9002, 9003, 9004)

    def __init__(self):
        self.sockets = []
        self.fios = []
        self.a_correr = True

    def __enter__(self):
        for porta in self.PORTAS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind(("127.0.0.1", porta))
            except OSError:
                sock.close()
                self.__exit__(None, None, None)
                raise SystemExit(
                    f"IGNORADO: a porta de áudio {porta} está ocupada — fecha o bridge "
                    "ou o audio-server antes de correr este teste."
                )
            sock.settimeout(0.5)
            self.sockets.append(sock)
            fio = threading.Thread(target=self._atender, args=(sock,), daemon=True)
            fio.start()
            self.fios.append(fio)
        return self

    def _atender(self, sock):
        contador = 0
        while self.a_correr:
            try:
                dados, remetente = sock.recvfrom(4096)
            except (socket.timeout, OSError):
                continue
            try:
                comando = json.loads(dados.decode("utf-8"))
            except ValueError:
                continue
            contador += 1
            if comando.get("cmd") == "PLAY":
                resposta = {"instance_id": contador}
            else:
                resposta = {"success": True, "instance_id": comando.get("instance_id")}
            try:
                sock.sendto(json.dumps(resposta).encode("utf-8"), remetente)
            except OSError:
                pass

    def __exit__(self, *_):
        self.a_correr = False
        for sock in self.sockets:
            sock.close()
        return False


def escrever_qr():
    sys.path.insert(0, str(REPO / "bridge"))
    from qr import generate_qr

    generate_qr("https://smoke-test.trycloudflare.com/", str(QR))


def vivo(processo):
    return processo.poll() is None


def ecra_actual(registo):
    """Último ecrã que o jogo disse estar a mostrar (ver o `print` em game.py).

    Verificar só que o processo está vivo não chega — foi assim que uma versão
    presa para sempre no ecrã de espera passou neste teste. O que interessa é
    o que está na parede.
    """
    ultimo = None
    for linha in registo.read_text(errors="replace").splitlines():
        if linha.startswith("[ecrã] a mostrar: "):
            ultimo = linha.split(": ", 1)[1].strip()
    return ultimo


def esperar_por_ecra(processo, registo, limite, esperado=None):
    """Espera que o jogo diga em que ecrã está (ou que mude para `esperado`).

    Espera-se por um sinal do próprio jogo, nunca por um número de segundos
    escolhido a olho: o arranque leva ~32s nesta máquina e pode levar mais
    noutra, com a BigFile num disco mais lento.
    """
    inicio = time.monotonic()
    partida = ecra_actual(registo)
    while time.monotonic() - inicio < limite:
        if not vivo(processo):
            return False
        actual = ecra_actual(registo)
        if esperado is None:
            if actual is not None:
                return True
        elif actual == esperado and actual != partida:
            return True
        time.sleep(0.5)
    return False


def falhar(processo, fase, registo):
    saida = registo.read_text(errors="replace")[-2000:]
    print(f"FALHOU em: {fase}\n--- últimas linhas ---\n{saida}")
    if vivo(processo):
        processo.kill()
    raise SystemExit(1)


def main() -> int:
    if not Path(ASSETS).is_dir():
        print(f"IGNORADO: não encontrei a BigFile em {ASSETS}")
        return 0
    if not VENV_PY.is_file():
        print(f"IGNORADO: não encontrei a .venv em {VENV_PY}")
        return 0

    registo = Path("/tmp/hugo-smoke.log")
    QR.unlink(missing_ok=True)  # começa como um arranque de evento: sem QR

    audio = RespondedorDeAudio().__enter__()
    lancado = time.monotonic()
    with registo.open("w") as saida:
        jogo = subprocess.Popen(
            [str(VENV_PY), "-u", "game.py", ASSETS],
            cwd=str(AQUI),
            stdout=saida,
            stderr=subprocess.STDOUT,
        )
    try:
        # O jogo leva ~32s a chegar ao ciclo de render: 27s só a carregar
        # recursos (medido nesta máquina, com a BigFile real). Até lá não
        # desenha nada e não diz nada, e uma versão anterior deste teste
        # media aos 7s — dava tudo por bom sobre um jogo que ainda nem tinha
        # pintado o primeiro frame. Espera-se pela marca, não pelo relógio.
        #
        # O ecrã de espera tem de estar pintado ANTES desses 27s, não depois.
        # Durante muito tempo esteve depois: mostrava-se o loading.png de
        # origem durante todo o carregamento, e o nosso ecrã com os logótipos
        # só teria a sua vez a seguir — altura em que o QR já existe e ele
        # nunca chega a aparecer. Nenhum teste via isto, porque todos
        # começavam a olhar a partir do ciclo de render.
        if not esperar_por_ecra(jogo, registo, limite=45):
            falhar(jogo, "o jogo não pintou nada em 45s", registo)
        ao_fim_de = time.monotonic() - lancado
        estado = ecra_actual(registo)
        if estado != "espera (a carregar recursos)":
            falhar(
                jogo,
                f"a primeira coisa pintada devia ser o ecrã de espera, foi {estado!r} "
                "— o carregamento voltou a passar à frente dele",
                registo,
            )
        # Não chega ser o primeiro: tem de ser CEDO. Medido nesta máquina, o
        # ecrã de espera aparece a 1,6s e o ciclo de render a 32,8s. Se alguém
        # empurrar a pintura para depois do carregamento, ela passa a aparecer
        # perto dos 32s — e continuaria a ser a primeira marca, portanto a
        # ordem sozinha não apanhava a regressão.
        if ao_fim_de > 12:
            falhar(
                jogo,
                f"o ecrã de espera só apareceu ao fim de {ao_fim_de:.1f}s — devia estar "
                "no ecrã em poucos segundos, senão não cobre o carregamento",
                registo,
            )
        print(f"OK 1: ecrã de espera pintado a {ao_fim_de:.1f}s, antes de carregar os recursos")

        if not esperar_por_ecra(jogo, registo, limite=90, esperado="espera (sem QR)"):
            falhar(jogo, "o jogo não chegou ao ciclo de render em 90s", registo)
        print("OK 2: sem QR em disco, o ciclo de render fica no ecrã de espera")

        # A transição que rebentava com NameError. E, antes disso, a que nem
        # sequer acontecia: com a condição errada o ecrã ficava preso aqui.
        escrever_qr()
        esperar_por_ecra(jogo, registo, limite=15, esperado="convites")
        if not vivo(jogo):
            falhar(jogo, "transição ecrã de espera -> convites (o QR apareceu)", registo)
        estado = ecra_actual(registo)
        if estado != "convites":
            falhar(
                jogo,
                f"com QR em disco devia mostrar os convites, mostra {estado!r} "
                "— ou ficou preso na espera, ou rebentou a desenhar",
                registo,
            )
        print("OK 3: o QR apareceu e o ecrã passou aos convites")

        # E o caminho de volta, que acontece quando o bridge reinicia.
        QR.unlink(missing_ok=True)
        esperar_por_ecra(jogo, registo, limite=15, esperado="espera (sem QR)")
        if not vivo(jogo):
            falhar(jogo, "convites -> ecrã de espera (o QR desapareceu)", registo)
        estado = ecra_actual(registo)
        if estado != "espera (sem QR)":
            falhar(jogo, f"QR desapareceu; devia voltar à espera, está em {estado!r}", registo)
        print("OK 4: o QR desapareceu e o ecrã voltou à espera (reinício do bridge)")
    finally:
        if vivo(jogo):
            jogo.terminate()
            try:
                jogo.wait(timeout=10)
            except subprocess.TimeoutExpired:
                jogo.kill()
        audio.__exit__(None, None, None)
        QR.unlink(missing_ok=True)

    texto = registo.read_text(errors="replace")
    for marca in ("Traceback", "NameError", "AttributeError"):
        assert marca not in texto, f"{marca} no log do jogo:\n{texto[-1500:]}"
    print("OK 5: nenhum traceback no log")
    print("Todos os cenários passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
