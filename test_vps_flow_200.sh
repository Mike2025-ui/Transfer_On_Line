#!/bin/bash
set -u

BASE_URL="${BASE_URL:-https://transfert-online.site}"
OPERATOR_ID="${OPERATOR_ID:-}"
SERVICE_ID="${SERVICE_ID:-}"
PHONE="${PHONE:-22501020304}"
AMOUNT="${AMOUNT:-200}"
GATEWAY_SECRET="${GATEWAY_SECRET:-}"
ID_KEY="${ID_KEY:-vps-test-200-$(date +%s)}"
TIMEOUT="${TIMEOUT:-20}"

printf '=== TEST FLUX VPS (montant par défaut: 200 FCFA) ===\n'
printf 'BASE_URL=%s\n' "$BASE_URL"
printf 'OPERATOR_ID=%s\n' "${OPERATOR_ID:-auto}"
printf 'SERVICE_ID=%s\n' "${SERVICE_ID:-auto}"
printf 'PHONE=%s\n' "$PHONE"
printf 'AMOUNT=%s\n' "$AMOUNT"
printf 'ID_KEY=%s\n' "$ID_KEY"
printf '====================\n'

fetch_first_id() {
  local api_url="$1"
  local key="$2"
  local tmp_headers="$(mktemp)"
  local tmp_body="$(mktemp)"

  curl -sS -L --max-time "$TIMEOUT" -D "$tmp_headers" -o "$tmp_body" "$api_url" || return 1

  local http_status
  http_status=$(awk 'NR==1 {print $2}' "$tmp_headers")
  if [ -n "$http_status" ] && [ "$http_status" != "200" ]; then
    echo "HTTP_STATUS:$http_status" >&2
    echo "RAW_BODY:" >&2
    cat "$tmp_body" >&2
    return 1
  fi

  if [ ! -s "$tmp_body" ]; then
    echo "EMPTY_BODY" >&2
    return 1
  fi

  python3 - "$key" "$tmp_body" <<'PY'
import json, sys
key = sys.argv[1]
path = sys.argv[2]
try:
    with open(path, 'r', encoding='utf-8') as f:
        body = f.read()
    data = json.loads(body)
except Exception as exc:
    print(f"INVALID_JSON:{exc}", file=sys.stderr)
    print(body if 'body' in locals() else '', file=sys.stderr)
    raise SystemExit(1)

if isinstance(data, list):
    for item in data:
        if isinstance(item, dict):
            if item.get('is_active', True) is not False:
                print(item.get(key, ''))
                raise SystemExit(0)
elif isinstance(data, dict):
    items = data.get('results') if isinstance(data.get('results'), list) else data.get('data')
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get('is_active', True) is not False:
                print(item.get(key, ''))
                raise SystemExit(0)
print('', end='')
PY
}

if [ -z "$OPERATOR_ID" ]; then
  OPERATOR_ID="$(fetch_first_id "$BASE_URL/api/operators/" 'id')"
fi

if [ -z "$SERVICE_ID" ]; then
  SERVICE_ID="$(fetch_first_id "$BASE_URL/api/services/" 'id')"
fi

if [ -z "$OPERATOR_ID" ] || [ -z "$SERVICE_ID" ]; then
  printf 'Aucun opérateur ou service actif trouvé via l\'API.\n'
  printf 'Vérifie : %s/api/operators/ et %s/api/services/\n' "$BASE_URL" "$BASE_URL"
  exit 1
fi

printf 'Valeurs réellement utilisées : operator_id=%s service_id=%s\n' "$OPERATOR_ID" "$SERVICE_ID"

printf '\n--- OPERATORS ---\n'
curl -sS --max-time "$TIMEOUT" "$BASE_URL/api/operators/"

printf '\n\n--- SERVICES ---\n'
curl -sS --max-time "$TIMEOUT" "$BASE_URL/api/services/"

create_body=$(cat <<EOF
{
  "operator_id": $OPERATOR_ID,
  "service_id": $SERVICE_ID,
  "phone": "$PHONE",
  "amount": $AMOUNT,
  "payment_method": "auto",
  "device_uid": "vps-test-device-001",
  "idempotency_key": "$ID_KEY"
}
EOF
)

printf '\n\n--- CREATE TRANSACTION ---\n'
create_resp=$(curl -sS --max-time "$TIMEOUT" -w "\nHTTP_STATUS:%{http_code}" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $ID_KEY" \
  -d "$create_body" \
  "$BASE_URL/api/transactions/execute/")

echo "$create_resp"

create_json=$(printf '%s' "$create_resp" | sed '/HTTP_STATUS:/,$d')
ref=$(printf '%s' "$create_json" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('reference',''))" 2>/dev/null || true)

printf 'REFERENCE=%s\n' "$ref"

if [ -z "$ref" ]; then
  printf '%s\n' "La transaction n'a pas été créée correctement."
  printf '%s\n' "Vérifie que l'API renvoie bien un reference pour operator_id=${OPERATOR_ID} et service_id=${SERVICE_ID}."
  exit 1
fi

for i in 1 2 3 4 5; do
  printf '\n--- STATUS POLL %s ---\n' "$i"
  curl -sS --max-time "$TIMEOUT" "$BASE_URL/api/transactions/$ref/status/"
  sleep 1
done

if [ -n "$GATEWAY_SECRET" ]; then
  gateway_body=$(cat <<EOF
{
  "transaction_reference": "$ref",
  "success": true,
  "result": "Souscription réussie"
}
EOF
)

  printf '\n--- GATEWAY RESULT ---\n'
  curl -sS --max-time "$TIMEOUT" -w "\nHTTP_STATUS:%{http_code}" \
    -H "Content-Type: application/json" \
    -H "X-Gateway-Secret: $GATEWAY_SECRET" \
    -d "$gateway_body" \
    "$BASE_URL/api/transactions/result/"
else
  printf '\n%s\n' "Aucun GATEWAY_SECRET fourni. Test gateway ignoré."
  printf '%s\n' "Pour le tester, mets GATEWAY_SECRET dans l'environnement puis relance."
fi

printf '\n=== FIN DU TEST ===\n'
