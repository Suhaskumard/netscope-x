# Phase 06 development image: installs and builds the frontend placeholder scaffold.
# Served via `vite preview` for now; a production static-file server is chosen in a
# later phase once the real frontend (Phase 12+) exists.
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

EXPOSE 4173
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0"]
