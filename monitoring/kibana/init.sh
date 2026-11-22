#!/bin/sh
set -eu

KIBANA_URL="http://kibana:5601"

echo "Waiting for Kibana..."

attempt=0
until curl --fail --silent --show-error \
  --connect-timeout 5 --max-time 10 \
  "$KIBANA_URL/api/status" > /dev/null
do
  attempt=$((attempt + 1))

  if [ "$attempt" -ge 60 ]; then
    echo "Kibana did not become ready."
    exit 1
  fi

  sleep 5
done

echo "Importing Kibana saved objects..."

curl --fail-with-body --silent --show-error \
  --connect-timeout 5 --max-time 120 \
  -X POST "$KIBANA_URL/api/saved_objects/_import?overwrite=true" \
  -H "kbn-xsrf: true" \
  -F "file=@/setup/export.ndjson" \
  -o /tmp/import-result.json

cat /tmp/import-result.json

if ! grep -Eq '"success"[[:space:]]*:[[:space:]]*true' \
  /tmp/import-result.json; then
  echo "Kibana import failed."
  exit 1
fi

echo "Kibana import completed."