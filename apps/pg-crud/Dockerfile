# 빌드 스테이지
FROM golang:1.23-alpine AS builder

WORKDIR /app

COPY go.mod go.sum* ./
RUN go mod download

COPY main.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o pg-crud .

# 런타임 스테이지 (최소 이미지)
FROM scratch

COPY --from=builder /app/pg-crud /pg-crud

EXPOSE 8080

ENTRYPOINT ["/pg-crud"]
