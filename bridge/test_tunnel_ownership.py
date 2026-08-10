"""Quem é que o `_varrer_orfaos()` pode mesmo matar.

    ../.venv/bin/python test_tunnel_ownership.py        (a partir de bridge/)

Isto existe porque a primeira versão identificava o processo por PID mais
linha de comando, e isso não identifica nada: o sistema reaproveita PIDs, e
nada impede que o PID reaproveitado seja OUTRO `cloudflared tunnel --url` para
a mesma porta — aberto à mão pelo operador, por exemplo. A verificação passava
e mandávamos SIGTERM ao processo dele. O teste que existia antes só cobria o
caso fácil (PID reaproveitado por um comando diferente).

O que se prova aqui é a decisão, não o `ps`: substitui-se a leitura da
identidade e regista-se para onde iria o sinal. O último cenário é real —
processo verdadeiro, `ps` verdadeiro — para garantir que a identidade que
guardamos é mesmo a que voltamos a ler.
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tunnel import QuickTunnel  # noqa: E402


def _tunel(tmp: Path) -> QuickTunnel:
    return QuickTunnel(8080, pid_path=tmp / "cloudflared.pid")


def _preparar(tunel: QuickTunnel, identidade_actual):
    """Troca a leitura da identidade e apanha o sinal em vez de o enviar."""
    mortos = []
    tunel._identidade_do_processo = lambda pid: identidade_actual  # type: ignore[method-assign]
    import tunnel as modulo

    original = modulo.os.kill
    modulo.os.kill = lambda pid, sinal: mortos.append(pid)  # type: ignore[assignment]
    return mortos, lambda: setattr(modulo.os, "kill", original)


ARRANQUE = "Sun Aug 10 07:54:01 2026"
COMANDO = "cloudflared tunnel --url http://127.0.0.1:8080"
NOSSA = f"{ARRANQUE} {COMANDO}"


def cenario_orfao_nosso(tmp: Path) -> None:
    """O caso que isto serve: sobrou o nosso cloudflared, tem de morrer."""
    tunel = _tunel(tmp)
    tunel.pid_path.parent.mkdir(parents=True, exist_ok=True)
    tunel.pid_path.write_text(f"4242\n{COMANDO}\n{NOSSA}\n", encoding="utf-8")
    mortos, repor = _preparar(tunel, NOSSA)
    try:
        assert tunel._varrer_orfaos() == 1
        assert mortos == [4242], mortos
    finally:
        repor()
    assert not tunel.pid_path.exists(), "o registo devia ficar limpo"


def cenario_pid_reutilizado_por_outro_comando(tmp: Path) -> None:
    tunel = _tunel(tmp)
    tunel.pid_path.parent.mkdir(parents=True, exist_ok=True)
    tunel.pid_path.write_text(f"4242\n{COMANDO}\n{NOSSA}\n", encoding="utf-8")
    mortos, repor = _preparar(tunel, "Mon Aug 11 09:00:00 2026 /usr/bin/python3 -m http.server")
    try:
        assert tunel._varrer_orfaos() == 0
        assert mortos == [], "não é nosso, não se toca"
    finally:
        repor()


def cenario_pid_reutilizado_pelo_mesmo_comando(tmp: Path) -> None:
    """O buraco que a revisão apanhou: mesmo PID, mesma assinatura, outro processo.

    Um segundo `cloudflared tunnel --url` para a mesma porta, do operador, que
    calhou de apanhar o PID que o nosso deixou. Só a hora de arranque os
    distingue.
    """
    tunel = _tunel(tmp)
    tunel.pid_path.parent.mkdir(parents=True, exist_ok=True)
    tunel.pid_path.write_text(f"4242\n{COMANDO}\n{NOSSA}\n", encoding="utf-8")
    mortos, repor = _preparar(tunel, f"Sun Aug 10 08:31:17 2026 {COMANDO}")
    try:
        assert tunel._varrer_orfaos() == 0
        assert mortos == [], "nasceu noutra hora, é outro processo — não se mata"
    finally:
        repor()


def cenario_processo_ja_morreu(tmp: Path) -> None:
    tunel = _tunel(tmp)
    tunel.pid_path.parent.mkdir(parents=True, exist_ok=True)
    tunel.pid_path.write_text(f"4242\n{COMANDO}\n{NOSSA}\n", encoding="utf-8")
    mortos, repor = _preparar(tunel, None)
    try:
        assert tunel._varrer_orfaos() == 0
        assert mortos == []
    finally:
        repor()


def cenario_registo_sem_identidade(tmp: Path) -> None:
    """Registo antigo, ou `ps` falhou ao arrancar: não se mata às cegas."""
    tunel = _tunel(tmp)
    tunel.pid_path.parent.mkdir(parents=True, exist_ok=True)
    tunel.pid_path.write_text(f"4242\n{COMANDO}\n", encoding="utf-8")
    mortos, repor = _preparar(tunel, NOSSA)
    try:
        assert tunel._varrer_orfaos() == 0
        assert mortos == [], "sem prova de propriedade, deixa-se em paz"
    finally:
        repor()


def cenario_outra_porta(tmp: Path) -> None:
    tunel = _tunel(tmp)
    tunel.pid_path.parent.mkdir(parents=True, exist_ok=True)
    outro = "cloudflared tunnel --url http://127.0.0.1:9999"
    tunel.pid_path.write_text(f"4242\n{outro}\n{ARRANQUE} {outro}\n", encoding="utf-8")
    mortos, repor = _preparar(tunel, f"{ARRANQUE} {outro}")
    try:
        assert tunel._varrer_orfaos() == 0
        assert mortos == []
    finally:
        repor()


def cenario_identidade_real(tmp: Path) -> None:
    """Com um processo a sério: o que se guarda é o que se volta a ler.

    Sem isto, todos os cenários acima podiam estar a concordar sobre um
    formato de `ps` que a máquina não produz.
    """
    proc = subprocess.Popen(["sleep", "30"])
    try:
        time.sleep(0.2)
        tunel = _tunel(tmp)
        identidade = tunel._identidade_do_processo(proc.pid)
        assert identidade is not None, "o `ps` não deu nada para um processo vivo"
        assert identidade.endswith("sleep 30"), identidade
        assert len(identidade.split()) >= 7, f"falta a hora de arranque: {identidade!r}"
        assert tunel._identidade_do_processo(proc.pid) == identidade, "não é estável"
    finally:
        proc.kill()
        proc.wait()
    assert tunel._identidade_do_processo(proc.pid) is None, "morto devia dar None"


def main() -> int:
    cenarios = [
        cenario_orfao_nosso,
        cenario_pid_reutilizado_por_outro_comando,
        cenario_pid_reutilizado_pelo_mesmo_comando,
        cenario_processo_ja_morreu,
        cenario_registo_sem_identidade,
        cenario_outra_porta,
        cenario_identidade_real,
    ]
    for cenario in cenarios:
        with tempfile.TemporaryDirectory() as pasta:
            cenario(Path(pasta))
        print(f"OK {cenario.__name__}")
    print(f"Todos os {len(cenarios)} cenários passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
