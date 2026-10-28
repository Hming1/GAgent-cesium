#!/bin/sh
# Substitute environment variables in the Nginx config template and output the final config
# Provide sensible defaults so the container does not fall back to Nginx defaults when
# variables are missing.
: "${BACKEND_PROTOCOL:=http}"
: "${BACKEND_URL:=backend:8000}"
: "${FRONTEND_PROTOCOL:=http}"
: "${FRONTEND_URL:=frontend:3000}"
: "${SECOND_FRONTEND_PROTOCOL:=http}"
: "${SECOND_FRONTEND_URL:=host.docker.internal:3001}"
# Default to Docker internal DNS; allow a resolver override for other deployments.
: "${DNS_RESOLVER:=127.0.0.11}"

echo "[entrypoint] Using BACKEND_PROTOCOL=${BACKEND_PROTOCOL}"
echo "[entrypoint] Using BACKEND_URL=${BACKEND_URL}"
echo "[entrypoint] Using FRONTEND_PROTOCOL=${FRONTEND_PROTOCOL}"
echo "[entrypoint] Using FRONTEND_URL=${FRONTEND_URL}"
echo "[entrypoint] Using SECOND_FRONTEND_PROTOCOL=${SECOND_FRONTEND_PROTOCOL}"
echo "[entrypoint] Using SECOND_FRONTEND_URL=${SECOND_FRONTEND_URL}"
echo "[entrypoint] Using DNS_RESOLVER=${DNS_RESOLVER}"

envsubst '$BACKEND_PROTOCOL $BACKEND_URL $FRONTEND_PROTOCOL $FRONTEND_URL $SECOND_FRONTEND_PROTOCOL $SECOND_FRONTEND_URL $DNS_RESOLVER' < /etc/nginx/nginx.conf.envsubst > /etc/nginx/nginx.conf
# Execute the command passed to the entrypoint (nginx)
exec "$@"
