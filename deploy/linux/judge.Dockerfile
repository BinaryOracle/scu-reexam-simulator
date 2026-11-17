FROM python:3.12-alpine
RUN sed -i 's#https://dl-cdn.alpinelinux.org/alpine#https://mirrors.aliyun.com/alpine#' /etc/apk/repositories \
    && apk add --no-cache build-base
LABEL scu.coding.languages="cpp11,c,python3"
WORKDIR /app
