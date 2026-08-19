"""Trocar de modo com o bridge a andar, do botão até à mensagem que o jogo lê.

    ../.venv/bin/python test_mode_switch.py        (a partir de bridge/)

Isto arranca o bridge a sério, num config próprio (sem túnel, sem áudio, sem
pontuação), põe-se à escuta na porta do JOGO e manda o mesmo datagrama que o
botão do ecrã grande manda. O que se exige é a única coisa que interessa em
palco: que a mensagem `slots` que o jogo recebe passe a dizer o modo novo.

Testar as peças à parte não chegava aqui. O modo vive em três sítios ao mesmo
tempo — o carimbo do emissor UDP, o `input_mode` que a webapp recebe, e o
adaptador SIP estar ligado ou não — e o defeito provável não é nenhuma das
peças estar errada, é ficar uma para trás. Só um teste que atravesse tudo vê
isso.
"""
import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
VENV_PY = REPO / ".venv" / "bin" / "python3"

PORTA_JOGO = 9190       # portas próprias, para nunca colidir com um bridge a sério
PORTA_WEB = 8190
PORTA_CONTROLO = 9191

CONFIG = f"""
input_mode: web
game:
  host: 127.0.0.1
  port: {PORTA_JOGO}
web:
  host: 127.0.0.1
  port: {PORTA_WEB}
control:
  host: 127.0.0.1
  port: {PORTA_CONTROLO}
tunnel:
  enabled: false
bridge:
  slots: 4
  inactivity_timeout_seconds: 120
  offer_timeout_seconds: 15
  dedup_window_ms: 60
  sip_preempt: false
sip:
  esl_host: 127.0.0.1
  esl_port: 8921
  esl_password: ClueCon
  context: hugo-lan
"""


def esperar_modo(sock, esperado, limite=15.0):
    """Devolve True assim que chegar uma mensagem `slots` com o modo pedido."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        sock.settimeout(max(0.1, fim - time.monotonic()))
        try:
            dados, _ = sock.recvfrom(4096)
        except socket.timeout:
            break
        except OSError:
            continue
        try:
            msg = json.loads(dados.decode("utf-8"))
        except ValueError:
            continue
        if msg.get("type") == "slots" and msg.get("mode") == esperado:
            return True
    return False


def pedir(modo, porta=PORTA_CONTROLO):
    """O mesmo datagrama que game/mode_button.py manda."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(json.dumps({"cmd": "input_mode", "mode": modo}).encode("utf-8"),
                 ("127.0.0.1", porta))
    finally:
        s.close()


def controlo_recusa_fora_do_loopback():
    """A porta de controlo não pode acabar exposta à rede do evento."""
    sys.path.insert(0, str(AQUI))
    from control import start_control_listener

    async def nunca(_modo):
        raise AssertionError("não devia chegar aqui")

    async def tentar():
        try:
            await start_control_listener(nunca, host="0.0.0.0", port=PORTA_CONTROLO)
        except ValueError:
            return True
        return False

    assert asyncio.run(tentar()), "0.0.0.0 devia ser recusado"
    print("OK 1: o canal de controlo recusa-se a escutar fora do loopback")


def main() -> int:
    if not VENV_PY.is_file():
        print(f"IGNORADO: não encontrei a .venv em {VENV_PY}")
        return 0

    controlo_recusa_fora_do_loopback()

    jogo = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    jogo.bind(("127.0.0.1", PORTA_JOGO))

    with tempfile.TemporaryDirectory() as pasta:
        config = Path(pasta) / "config.yaml"
        config.write_text(CONFIG, encoding="utf-8")
        registo = Path(pasta) / "bridge.log"
        with registo.open("w") as saida:
            bridge = subprocess.Popen(
                [str(VENV_PY), "-u", str(REPO / "bridge" / "main.py"), "--config", str(config)],
                cwd=str(REPO),
                stdout=saida,
                stderr=subprocess.STDOUT,
            )
        try:
            if not esperar_modo(jogo, "web", limite=20):
                raise AssertionError(
                    "o bridge não chegou a anunciar o modo web:\n"
                    + registo.read_text(errors="replace")[-1500:]
                )
            print("OK 2: o bridge arranca a anunciar o modo do config (web)")

            pedir("sip")
            if not esperar_modo(jogo, "sip"):
                raise AssertionError(
                    "pedi sip e o jogo continuou a receber outro modo:\n"
                    + registo.read_text(errors="replace")[-1500:]
                )
            print("OK 3: o botão troca para telefones e o jogo dá por isso")

            pedir("web")
            if not esperar_modo(jogo, "web"):
                raise AssertionError("não voltou a web")
            print("OK 4: e volta atrás")

            # Lixo no canal não pode derrubar o bridge — é a mesma porta que
            # qualquer processo local pode alcançar.
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for lixo in (b"nao-e-json", b'{"cmd":"outra-coisa"}', b'{"cmd":"input_mode"}',
                         b'{"cmd":"input_mode","mode":"telepatia"}', b'{"cmd":"input_mode","mode":7}'):
                s.sendto(lixo, ("127.0.0.1", PORTA_CONTROLO))
            s.close()
            pedir("sip")
            if not esperar_modo(jogo, "sip"):
                raise AssertionError("o bridge deixou de responder depois do lixo")
            print("OK 5: lixo no canal de controlo é ignorado e o bridge sobrevive")

            assert bridge.poll() is None, "o bridge morreu durante o teste"
        finally:
            # O bridge escreve o QR no sítio real (o caminho é fixo em
            # main.py). Deixá-lo lá punha no ecrã grande, à espera do próximo
            # arranque, um código para um lobby de teste que já não existe.
            (REPO / "game" / "resources" / "images" / "qr_lobby.png").unlink(missing_ok=True)
            bridge.terminate()
            try:
                bridge.wait(timeout=15)
            except subprocess.TimeoutExpired:
                bridge.kill()
            jogo.close()

    print("Todos os cenários passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
