#!/bin/bash
set -e

cd "$(dirname "$0")"

# Сборка Hugo
hugo --minify

# Копируем CSS в папки авторов
for platform in public/sponsr public/boosty; do
    [ -d "$platform" ] || continue
    for author in "$platform"/*/; do
        [ -d "$author" ] || continue
        cp -r public/css "$author"
        echo "CSS → $author"
    done
done

echo "Build complete"
