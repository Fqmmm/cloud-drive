FROM node:24-alpine@sha256:f36fed0b2129a8492535e2853c64fbdbd2d29dc1219ee3217023ca48aebd3787 AS build
WORKDIR /build
ARG NPM_REGISTRY=https://registry.npmjs.org
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm@10.32.1 --registry="${NPM_REGISTRY}" --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000 \
    && pnpm install --frozen-lockfile --ignore-scripts --registry="${NPM_REGISTRY}" --fetch-retries=5 --fetch-retry-mintimeout=10000 --fetch-retry-maxtimeout=60000
COPY index.html tsconfig.json vite.config.ts uno.config.ts ./
COPY src src
ARG VITE_MAX_FILE_BYTES=104857600
ENV VITE_MAX_FILE_BYTES=${VITE_MAX_FILE_BYTES}
RUN pnpm exec vue-tsc --noEmit && pnpm exec vite build

FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/course-proxy.conf /etc/nginx/course-proxy.conf
COPY --from=build /build/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1/healthz"]
