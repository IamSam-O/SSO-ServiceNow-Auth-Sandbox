FROM alpine:latest

RUN apk add --no-cache bash curl jq dos2unix

COPY entrypoint.sh /entrypoint.sh
COPY refresh.sh /refresh.sh
RUN dos2unix /entrypoint.sh /refresh.sh && chmod +x /entrypoint.sh /refresh.sh

ENTRYPOINT ["/entrypoint.sh"]