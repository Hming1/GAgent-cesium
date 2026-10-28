#!/bin/bash
# One-time migration of user-independent geospatial data from the app DB into the
# layers DB: PostGIS spatial tables (layer_*, upload_*) and the dataset_resources
# catalog + dataset_resources_search function.
#
# Run on a FRESH layers DB (created by db/init-layers-db.sh or manually).
#
# Usage:
#   SRC=postgresql://app:app@host:5432/app \
#   DST=postgresql://app:app@host:5432/layers \
#   bash db/migrate-geodata-to-layers.sh
set -euo pipefail
SRC="${SRC:?set SRC= source app database URL}"
DST="${DST:?set DST= target layers database URL}"

echo "==> Ensuring extensions in target"
psql "$DST" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS postgis;"
psql "$DST" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;" \
  || echo "   (vector unavailable; skip if catalog has no embeddings)"

echo "==> Copying dataset_resources table"
if psql "$SRC" -tA -c "SELECT to_regclass('public.dataset_resources')" | grep -q .; then
  pg_dump --no-owner --no-privileges -t dataset_resources "$SRC" | psql "$DST"
else
  echo "   not found in source; skipping"
fi

echo "==> Copying dataset_resources_search function"
if psql "$SRC" -tA -c "SELECT 1 FROM pg_proc WHERE proname='dataset_resources_search'" | grep -q 1; then
  psql "$SRC" -c "\sf dataset_resources_search" | psql "$DST"
else
  echo "   not found in source; skipping"
fi

echo "==> Copying PostGIS spatial tables"
TABLES=$(psql "$SRC" -tA -c "SELECT DISTINCT f_table_name FROM geometry_columns WHERE f_table_schema='public'")
if [ -z "$TABLES" ]; then
  echo "   no spatial tables found; skipping"
else
  for t in $TABLES; do
    echo "   - $t"
    pg_dump --no-owner --no-privileges -t "$t" "$SRC" | psql "$DST"
  done
fi

echo "==> Done. Verify:  psql \"$DST\" -c \"\dt\""
