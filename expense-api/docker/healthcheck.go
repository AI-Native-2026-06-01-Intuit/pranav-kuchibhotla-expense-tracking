// Tiny liveness/readiness probe for the distroless runtime image.
//
// Distroless ships no shell, curl, or wget, so Docker's HEALTHCHECK needs a
// self-contained binary. This program does a single GET against the local
// Spring Boot actuator readiness endpoint and exits 0 iff the response is 2xx.
//
// Build both linux/arm64 (Rancher Desktop on aarch64) and linux/amd64
// (GitHub Actions ubuntu-22.04). The Dockerfile selects the right one
// at build time via the BuildKit-provided TARGETARCH.
//
//   docker run --rm -v "$PWD":/src -w /src golang:1.26.5-alpine sh -c '\
//     CGO_ENABLED=0 GOOS=linux GOARCH=arm64 \
//       go build -trimpath -ldflags="-s -w" -o healthcheck-arm64 healthcheck.go && \
//     CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
//       go build -trimpath -ldflags="-s -w" -o healthcheck-amd64 healthcheck.go'
//
// Both binaries are committed alongside this source so the runtime
// Dockerfile does not need a Go build stage.
package main

import (
	"net/http"
	"os"
	"time"
)

func main() {
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get("http://127.0.0.1:8080/actuator/health/readiness")
	if err != nil {
		os.Exit(1)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		os.Exit(1)
	}
	os.Exit(0)
}
