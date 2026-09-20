FROM node:24-alpine AS build
WORKDIR /project/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
COPY evidence/ /project/evidence/
COPY capabilities/ /project/capabilities/
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /project/frontend/dist /usr/share/nginx/html
EXPOSE 8080
