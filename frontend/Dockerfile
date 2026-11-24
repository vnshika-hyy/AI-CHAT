# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# The browser calls the backend directly, so its URL is baked in at build time
ARG VITE_API_URL=http://localhost:8000
ARG VITE_SHOW_TEST_TOOLS=true
ENV VITE_API_URL=$VITE_API_URL VITE_SHOW_TEST_TOOLS=$VITE_SHOW_TEST_TOOLS
RUN npm run build

# ---- runtime stage: static files behind unprivileged nginx ----
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
