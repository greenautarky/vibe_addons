# GreenAutarky rebuild of the SONOFF dongle-flasher VENDOR image.
#
# The vendor publishes no Dockerfile we could build from, and its image stops at
# 1.3.4 on an Alpine 3.21 base from 2025-11. Instead of copying those bytes
# unchanged (the old mirror), we take the vendor image as the base and refresh
# the operating-system layer on top of it, plus one targeted npm package:
#   * `apk upgrade` — every Alpine 3.21 package to the current 3.21 release;
#   * nodejs / npm — the vendor pinned exact versions in /etc/apk/world, which
#     `apk upgrade` honours; re-adding them unpinned lets them move to the
#     current 3.21 patch release (same Node 22 major, same ABI);
#   * tempio — the helper binary from the Home Assistant base image, replaced by
#     a current upstream release, verified against a pinned sha256;
#   * proxy-addr — one npm dependency of the vendor application (via express),
#     raised to a fixed release (second RUN below).
# The vendor application code (/workspace/src) is not touched.
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

# proxy-addr: the vendor app's express depends on proxy-addr ^2.0.7, installed
# once at /workspace/node_modules/proxy-addr. 2.0.8 declares the same
# dependencies (forwarded 0.2.0, ipaddr.js 1.9.1), so the package directory is
# swapped for the registry tarball, verified against its pinned npm integrity.
# Deliberately NOT `npm install`: that reconciles the whole vendor tree against
# its lockfile (devDependencies, the native serialport build) — far more than
# one package. npm-pin.js also updates the package-lock entry, so lockfile
# readers see what node_modules holds, and FAILS the build unless every copy of
# proxy-addr in the image is >= PROXY_ADDR_VERSION and express resolves it.
ARG PROXY_ADDR_VERSION=2.0.8
ARG PROXY_ADDR_INTEGRITY=sha512-5nnx0yGyVUcY6t9RnWcARWtwT9F1D8O9rt08htPvnd49W1IgZtmLkhu9WfMzQj1cFxjHIO6connUNVW5k7AVyQ==
COPY npm-pin.js /tmp/npm-pin.js
RUN set -eux; \
    curl -fsSL -o /tmp/pkg.tgz \
      "https://registry.npmjs.org/proxy-addr/-/proxy-addr-${PROXY_ADDR_VERSION}.tgz"; \
    node /tmp/npm-pin.js install proxy-addr "${PROXY_ADDR_VERSION}" "${PROXY_ADDR_INTEGRITY}" /tmp/pkg.tgz; \
    node /tmp/npm-pin.js assert proxy-addr "${PROXY_ADDR_VERSION}"; \
    rm -f /tmp/pkg.tgz /tmp/npm-pin.js
