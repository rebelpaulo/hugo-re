#!/bin/bash
# Constrói bridge/freeswitch/conf/ — a pasta que se aponta ao FreeSWITCH com
# -conf (ver scripts/macos/run-sip.sh). Gerada de novo a cada chamada, NÃO
# versionada (ver bridge/freeswitch/.gitignore).
#
# Porquê gerar em vez de copiar a árvore toda para o repositório: a
# configuração de origem do FreeSWITCH (Homebrew) tem centenas de ficheiros
# que não nos dizem respeito (idiomas, IVRs de exemplo, chatplan...) e que
# não queremos duplicar nem manter sincronizados à mão. Em vez disso: uma
# "quinta de symlinks" para tudo o que não mexemos — o mesmo truque que o
# próprio Homebrew já usa em /opt/homebrew/etc/freeswitch -> Cellar — com os
# nossos ficheiros reais (bridge/freeswitch/overrides/) por cima,
# substituindo exactamente o que precisa de ser diferente. Reproduzível:
# corre isto outra vez e sai sempre o mesmo resultado, em qualquer máquina
# com o FreeSWITCH instalado por Homebrew.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERRIDES="$SCRIPT_DIR/overrides"
CONF_DIR="$SCRIPT_DIR/conf"

BASE="$(brew --prefix freeswitch 2>/dev/null || true)/etc/freeswitch"
if [[ ! -d "$BASE" ]]; then
  echo "[FALHA] não encontrei a configuração base do FreeSWITCH via 'brew --prefix freeswitch'." >&2
  echo "        Confirma que 'brew install freeswitch' está feito." >&2
  exit 1
fi

rm -rf "$CONF_DIR"
mkdir -p "$CONF_DIR"

# 1) symlink para tudo o que existe na base, item a item no topo — assim
#    conseguimos substituir sub-pastas inteiras (sip_profiles, dialplan,
#    autoload_configs) por uma mistura de link + ficheiro nosso, sem
#    symlinkar a pasta toda de uma vez.
for item in "$BASE"/*; do
  ln -s "$item" "$CONF_DIR/$(basename "$item")"
done

# 2) sub-pastas onde substituímos ficheiros a sério: deixam de ser o symlink
#    do passo 1 e passam a pasta real nossa, com link para cada ficheiro de
#    origem + os nossos por cima (ganham em caso de mesmo nome).
overlay_dir() {
  local sub="$1"
  rm -f "$CONF_DIR/$sub"
  mkdir -p "$CONF_DIR/$sub"
  for item in "$BASE/$sub"/*; do
    ln -s "$item" "$CONF_DIR/$sub/$(basename "$item")"
  done
  if [[ -d "$OVERRIDES/$sub" ]]; then
    for item in "$OVERRIDES/$sub"/*; do
      [[ -e "$item" ]] || continue
      ln -sf "$item" "$CONF_DIR/$sub/$(basename "$item")"
    done
  fi
}
overlay_dir sip_profiles
overlay_dir dialplan
overlay_dir autoload_configs

# 3) ficheiros de topo que substituímos por inteiro (freeswitch.xml,
#    vars-lan.xml — este último não existe na base, é só nosso).
for item in "$OVERRIDES"/*.xml; do
  [[ -e "$item" ]] || continue
  ln -sf "$item" "$CONF_DIR/$(basename "$item")"
done

# 4) vars-lan.xml — gerado, não versionado: o IP do Mac na rede dos telefones.
#
# Porquê descobrir isto a cada arranque em vez de o escrever num ficheiro: com
# a Partilha de Internet do macOS ligada, os telefones ficam numa rede servida
# pelo próprio Mac (bridge100) e o endereço muda entre 192.168.2.1 e
# 192.168.3.1 conforme o sistema decide. O FreeSWITCH tem de atender NESSE
# endereço — foi medido que atender no IP do Wi-Fi, com o áudio a atravessar a
# tradução de endereços, atrasava as teclas dos telefones em segundos.
#
# Sem partilha ligada não há bridge100 nenhum: cai-se no que o FreeSWITCH já
# calculava sozinho, que é o comportamento de antes.
LAN_IP="$(ifconfig 2>/dev/null | awk '/^bridge1[0-9][0-9]:/{b=1} b && /inet /{print $2; exit}')"
if [[ -n "$LAN_IP" ]]; then
  printf '<X-PRE-PROCESS cmd="set" data="hugo_lan_ip=%s"/>\n' "$LAN_IP" > "$CONF_DIR/vars-lan.xml"
  echo "[OK] telefones atendidos em $LAN_IP (rede da Partilha de Internet)"
else
  printf '<X-PRE-PROCESS cmd="set" data="hugo_lan_ip=$${local_ip_v4}"/>\n' > "$CONF_DIR/vars-lan.xml"
  echo "[OK] sem Partilha de Internet — telefones atendidos no IP principal"
fi

echo "[OK] bridge/freeswitch/conf/ construído a partir de $BASE"
