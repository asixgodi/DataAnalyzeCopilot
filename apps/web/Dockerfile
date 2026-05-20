FROM node:22-alpine AS builder

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web/ .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

EXPOSE 3000
CMD ["npx", "next", "start", "--port", "3000"]
