#!/bin/bash
# Sobe (ou reinicia) o coletor como serviço do usuário: sobrevive ao fim da sessão do terminal.
cd "$(dirname "$0")/../../.."
NODE=$HOME/.nvm/versions/node/v24.18.1/bin
systemctl --user stop coletor-maps 2>/dev/null; systemctl --user reset-failed coletor-maps 2>/dev/null
systemd-run --user --unit=coletor-maps -E PATH=$NODE:/usr/bin:/bin --working-directory="$PWD" $NODE/node automations/pesquisa-local/coletor/servidor.cjs >/dev/null
for i in $(seq 20); do curl -sf 127.0.0.1:5681/saude >/dev/null && { echo "coletor no ar"; exit 0; }; sleep 0.5; done
echo "coletor não subiu: journalctl --user -u coletor-maps"; exit 1
