#!/bin/bash
set -e

# Create a dedicated database for user-independent geospatial data:
# PostGIS spatial tables (layer_*, upload_*) and the dataset_resources catalog.
# Runs only on a fresh data volume (standard docker-entrypoint behavior).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	CREATE DATABASE layers;
EOSQL

# Enable PostGIS in the new database (the image only enables it in POSTGRES_DB).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname=layers <<-EOSQL
	CREATE EXTENSION IF NOT EXISTS postgis;
EOSQL
