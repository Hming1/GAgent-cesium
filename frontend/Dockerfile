# Note: Syntax directive commented out to avoid Docker Hub dependency
# # syntax=docker/dockerfile:1

### 1) deps stage: install and cache all dependencies ###
FROM node:26-slim AS deps

WORKDIR /app

# Copy lockfiles & package manifests
COPY package.json yarn.lock* package-lock.json* pnpm-lock.yaml* .npmrc* ./

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# Install via the available package manager
RUN \
  if [ -f yarn.lock ]; then yarn install --frozen-lockfile; \
  elif [ -f package-lock.json ]; then npm ci; \
  elif [ -f pnpm-lock.yaml ]; then corepack enable pnpm && pnpm install --frozen-lockfile; \
  else echo "Lockfile not found." && exit 1; \
  fi


### 2) builder stage: bring down the build deps & build the app ###
FROM node:26-slim AS builder

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

WORKDIR /app

# Install only what’s needed to compile any native modules (e.g. SWC, image libs, etc.)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 \
      build-essential \
      libc6-dev \
 && rm -rf /var/lib/apt/lists/*

# Copy node_modules from deps
COPY --from=deps /app/node_modules ./node_modules

# Copy rest of the project
COPY . .

# Build your Next.js app
RUN \
  if [ -f yarn.lock ]; then yarn build; \
  elif [ -f package-lock.json ]; then npm run build; \
  elif [ -f pnpm-lock.yaml ]; then corepack enable pnpm && pnpm build; \
  else echo "Lockfile not found." && exit 1; \
  fi


### 3) runner stage: production image ###
FROM node:26-slim AS runner

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's/security.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_OPTIONS="--max-old-space-size=512"\
    npm_config_registry="https://registry.npmmirror.com" \
    YARN_REGISTRY="https://registry.npmmirror.com"

# Create a non-root user
RUN groupadd --system nodejs && useradd --system --gid nodejs nextjs

# Copy built output from builder
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 🔧 Make sure the runtime user can write the file your entrypoint creates
RUN mkdir -p /app/public && chown -R nextjs:nodejs /app

USER nextjs

EXPOSE 3000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["node", "server.js"]

