# The TraceScan frontend, built and served as a standalone Next.js server.
# Built by docker-compose.yml (`docker compose --profile app up -d --build` at the repo root).

FROM node:24.22.3-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

FROM node:24.22.3-slim AS build
WORKDIR /app
# Where the /api rewrite sends calls. Next writes the rewrites into the build, so this is fixed
# here, not when the server starts: the backend's name on the Compose network.
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=${BACKEND_URL} \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# frontend/.env.local is mounted for this step only, as a build secret, so it never lands in a
# layer: Next inlines NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY into the browser code (it is public) and
# the prerender reads the Clerk keys. The secret key comes again at runtime, from env_file.
RUN --mount=type=secret,id=frontend_env,target=/app/.env.local npm run build

FROM node:24.22.3-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/sign-in').then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
CMD ["node", "server.js"]
