#!/usr/bin/env bash
# Builds what the session runs, natively on Windows (Git Bash), from the repo root:
#   node/node_modules             npm ci (Express 5, bcrypt 6 with its win32-x64 prebuild, bcryptjs 3)
#   build/login-spring.jar        Spring Boot fat jar (Temurin JDK 25; Maven unpacked into tools/)
# Every cache (npm, Maven repository) stays under .cache/, so nothing lands outside this folder.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd -W 2>/dev/null || pwd)
MAVEN_VERSION=3.9.11
MAVEN_SHA512=03e2d65d4483a3396980629f260e25cac0d8b6f7f2791e4dc20bc83f9514db8d0f05b0479e699a5f34679250c49c8e52e961262ded468a20de0be254d8207076
JAVA_HOME=${BENCH_JAVA_HOME:-$(ls -d "/c/Program Files/Eclipse Adoptium"/jdk-25* | tail -1)}
export JAVA_HOME PATH="/c/Program Files/nodejs:$PATH" npm_config_cache="$ROOT/.cache/npm"
mkdir -p build tools .cache

node --version
(cd node && npm ci --no-audit --no-fund --loglevel=error)

MVN="tools/apache-maven-$MAVEN_VERSION/bin/mvn"
if [ ! -x "$MVN" ]; then
  zip="tools/maven.zip"
  curl -fsSL -o "$zip" "https://archive.apache.org/dist/maven/maven-3/$MAVEN_VERSION/binaries/apache-maven-$MAVEN_VERSION-bin.zip"
  echo "$MAVEN_SHA512  $zip" | sha512sum -c -
  unzip -q "$zip" -d tools && rm "$zip"
fi
"$JAVA_HOME/bin/java" -version
(cd java && "../$MVN" -B -q -Dmaven.repo.local="$ROOT/.cache/m2" package -DskipTests)
cp java/target/login-spring.jar build/
unzip -p build/login-spring.jar META-INF/MANIFEST.MF | tr -d '\r' | grep '^Spring-Boot-Version' > build/spring-boot-version.txt
ls -la build
