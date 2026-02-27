FROM node:20-alpine

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시)
COPY package.json .
RUN npm install --omit=dev

COPY index.js .

EXPOSE 8080

CMD ["node", "index.js"]
