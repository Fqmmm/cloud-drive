#!/bin/sh
# Retry dependency preparation only. Compile/tests run once and retain failures.
set -eu
goal="${1:-verify}"
case "$goal" in verify|package) ;; *) echo 'Unsupported Maven goal' >&2; exit 2 ;; esac
settings="$(mktemp "${TMPDIR:-/tmp}/course-maven.XXXXXX")"
trap 'rm -f "$settings"' EXIT HUP INT TERM
mirror="${MAVEN_MIRROR_URL:-}"
if [ -n "$mirror" ]; then
    if ! printf '%s\n' "$mirror" | grep -Eq '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._/-]*)?$'; then
        echo 'Maven mirror must be HTTPS without credentials or query parameters' >&2
        exit 2
    fi
    printf '<settings><mirrors><mirror><id>course-central</id><mirrorOf>central</mirrorOf><url>%s</url></mirror></mirrors></settings>\n' "$mirror" > "$settings"
else
    printf '<settings/>\n' > "$settings"
fi
ready=false
for attempt in 1 2 3; do
    echo "Preparing Maven dependencies: attempt $attempt/3"
    if mvn -s "$settings" -B -U -C -Dmaven.artifact.threads=2 org.apache.maven.plugins:maven-dependency-plugin:3.8.1:go-offline; then
        ready=true
        break
    fi
    if [ "$attempt" -lt 3 ]; then sleep 5; fi
done
if [ "$ready" != true ]; then
    echo 'Dependency preparation failed; compilation/tests were not started' >&2
    exit 1
fi
mvn -s "$settings" -B -C "$goal"
