# GreenAutarky rebuild of the SONOFF dongle-flasher VENDOR image.
#
# The vendor publishes no Dockerfile we could build from, and its image stops at
# 1.3.4 on an Alpine 3.21 base from 2025-11. Instead of copying those bytes
# unchanged (the old mirror), we take the vendor image as the base and refresh
# only the operating-system layer on top of it:
#   * `apk upgrade` — every Alpine 3.21 package to the current 3.21 release;
#   * nodejs / npm — the vendor pinned exact versions in /etc/apk/world, which
#     `apk upgrade` honours; re-adding them unpinned lets them move to the
#     current 3.21 patch release (same Node 22 major, same ABI);
#   * tempio — the helper binary from the Home Assistant base image, replaced by
#     a current upstream release, verified against a pinned sha256.
# The vendor application (/workspace) is not touched.
ARG SRC_IMAGE
FROM ${SRC_IMAGE}

ARG BUILD_ARCH
ARG TEMPIO_VERSION=2026.07.0

# hadolint ignore=DL3017,DL3018
RUN set -eux; \
    apk add --no-cache --upgrade nodejs npm; \
    apk upgrade --no-cache; \
    case "${BUILD_ARCH}" in \
      armv7)   sha=1887c4721317ee166de703ddb30f906c9f98f01f08a6b2da295c10946a0c8110 ;; \
      aarch64) sha=dd846861a6829bdf1267b09d4735fc6ebd0cc748c73542eb9e721c9c4d833209 ;; \
      amd64)   sha=c03682e407110fa89475c0231cde5c4b5fd59660c7fc68e5ce5d2e703ed8c002 ;; \
      *) echo "unsupported BUILD_ARCH '${BUILD_ARCH}'"; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/tempio \
      "https://github.com/home-assistant/tempio/releases/download/${TEMPIO_VERSION}/tempio_${BUILD_ARCH}"; \
    echo "${sha}  /tmp/tempio" | sha256sum -c -; \
    install -m 0755 /tmp/tempio /usr/bin/tempio; \
    rm -f /tmp/tempio; \
    node --version; npm --version; tempio -h >/dev/null 2>&1 || true
