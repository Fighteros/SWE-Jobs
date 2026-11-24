FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY server.js inbound-spool.js ./

EXPOSE 8789

CMD ["node", "server.js"]
