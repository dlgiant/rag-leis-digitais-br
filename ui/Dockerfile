# Phase 10b — UI Docker image for Fly.io.
# Two-stage build: install + build in the first stage, copy the
# server bundle into a slim runtime image in the second.

FROM node:20-slim AS build
WORKDIR /app

# Install deps first (layer cached on package-lock.json)
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Build the Astro SSR bundle
COPY . .
RUN npm run build

# ---

FROM node:20-slim
WORKDIR /app

# Copy only the built artifacts + production deps
COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=4321

EXPOSE 4321

# Start the Astro Node server
CMD ["node", "./dist/server/entry.mjs"]
