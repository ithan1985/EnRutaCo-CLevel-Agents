#!/usr/bin/env bash
# Despliega un commit del repositorio en la instancia EC2 de la junta y reconstruye la API.
#
# Uso (desde WSL, dentro del repositorio):
#   bash scripts/desplegar_aws.sh <IP-pública> [ruta-a-la-llave.pem]
#
# Ejemplos:
#   bash scripts/desplegar_aws.sh 3.91.20.15                    # llave en ~/enrutaco.pem
#   APAGAR_EN=180 bash scripts/desplegar_aws.sh 3.91.20.15      # y programa el apagado en 3 horas
#
# Variables opcionales:
#   REF=HEAD        commit, rama o etiqueta a desplegar (por defecto HEAD: lo último que tiene commit)
#   APAGAR_EN=N     apaga la instancia en N minutos (red de seguridad de costos; se cancela con
#                   «ssh ... sudo shutdown -c»). Calcúlalo para que caiga DESPUÉS de la sesión.
#
# Qué hace: empaqueta el commit con git archive (no incluye .env, llaves ni archivos sin commit), lo copia a
# ~/app en la instancia conservando su .env, reconstruye y reinicia el contenedor api, espera a /api/health,
# precalienta el modelo rápido e imprime el comando del túnel SSH.
set -euo pipefail

IP="${1:-}"
PEM="${2:-$HOME/enrutaco.pem}"
REF="${REF:-HEAD}"
APAGAR_EN="${APAGAR_EN:-}"

if [[ -z "$IP" ]]; then
  echo "Uso: bash scripts/desplegar_aws.sh <IP-pública> [ruta-a-la-llave.pem]" >&2
  exit 1
fi
if [[ ! -f "$PEM" ]]; then
  echo "No encuentro la llave: $PEM" >&2
  echo "Cópiala a tu home de WSL:  cp /mnt/d/ruta/a/enrutaco.pem ~/ && chmod 400 ~/enrutaco.pem" >&2
  exit 1
fi
if [[ "$PEM" == /mnt/* ]]; then
  echo "Aviso: la llave está en una unidad de Windows (/mnt/...); ssh puede rechazarla por permisos." >&2
  echo "       Si falla: cp \"$PEM\" ~/ && chmod 400 ~/$(basename "$PEM")" >&2
fi
if [[ -n "$APAGAR_EN" && ! "$APAGAR_EN" =~ ^[0-9]+$ ]]; then
  echo "APAGAR_EN debe ser un número de minutos (ej.: APAGAR_EN=180)." >&2
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"
COMMIT="$(git rev-parse --short "$REF")"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Aviso: tienes cambios sin commit. Se despliega $REF ($COMMIT), no tu copia de trabajo."
fi

SSH_OPTS=(-i "$PEM" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 -o ServerAliveInterval=30)
# Ejecuta en la instancia el script que llega por la entrada estándar (sin comillas anidadas).
remoto() { ssh "${SSH_OPTS[@]}" "ubuntu@$IP" bash -s -- "$@"; }

TGZ="$(mktemp -t enrutaco-XXXXXX.tgz)"
trap 'rm -f "$TGZ"' EXIT
git archive --format=tar.gz -o "$TGZ" "$REF"

echo "1/5 Copiando $COMMIT a $IP…"
scp "${SSH_OPTS[@]}" -q "$TGZ" "ubuntu@$IP:/tmp/enrutaco-app.tgz"

echo "2/5 Descomprimiendo en ~/app (se conserva el .env de la instancia)…"
remoto "$COMMIT" <<'REMOTO'
set -e
mkdir -p ~/app
tar -xzf /tmp/enrutaco-app.tgz -C ~/app
cd ~/app
[ -f .env ] || cp .env.example .env
echo "$1" > ~/app/DESPLEGADO
REMOTO

echo "3/5 Reconstruyendo y reiniciando la API (2 a 4 minutos)…"
remoto <<'REMOTO'
set -e
cd ~/app
if docker ps >/dev/null 2>&1; then D=docker; else D="sudo docker"; fi
$D compose up -d --build --force-recreate api
REMOTO

echo "4/5 Esperando a la API…"
remoto <<'REMOTO'
for _ in $(seq 1 100); do curl -fsS localhost:8080/api/health >/dev/null 2>&1 && break; sleep 3; done
curl -fsS localhost:8080/api/health | python3 -c '
import json, sys
d = json.load(sys.stdin)
llm = d["llm"]
modelos = ", ".join(v["name"] + (" listo" if v["ready"] else " FALTA") for v in llm.get("models", {}).values())
print("   Ollama:", "responde" if llm.get("reachable") else "NO RESPONDE",
      "| modelos:", modelos or "-", "| voces:", "listas" if d["tts"].get("ready") else "cargando")
'
REMOTO

echo "5/5 Precalentando el modelo rápido…"
remoto <<'REMOTO' || echo "   (el precalentamiento falló; no es grave: la primera pregunta tardará un poco más)"
curl -fsS -m 180 -X POST localhost:8080/api/warmup -H "Content-Type: application/json" \
     -d '{"cid":"ti","junta":true}' | python3 -c '
import json, sys
d = json.load(sys.stdin)
s = d.get("stats") or {}
print("  ", d.get("status"), d.get("model"), "| carga", s.get("load_s"), "s | lectura del prompt", s.get("prefill_s"), "s")
'
REMOTO

if [[ -n "$APAGAR_EN" ]]; then
  remoto "$APAGAR_EN" <<'REMOTO' || true
sudo shutdown -h "+$1" >/dev/null 2>&1
REMOTO
  echo "Apagado programado en $APAGAR_EN minutos (cancelar: ssh -i $PEM ubuntu@$IP sudo shutdown -c)."
fi

cat <<FIN

Listo: $COMMIT desplegado en $IP.
Abre el túnel en otra terminal de WSL y déjala abierta durante toda la sesión:
  ssh -i $PEM -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -N -L 8081:localhost:8080 ubuntu@$IP
Luego abre en el navegador: http://localhost:8081
FIN
