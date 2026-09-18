#!/bin/bash
set -e

cd "$(dirname "$0")"

# Hardlinks из предыдущей сборки нельзя отдавать Hugo на перезапись.
rm -rf public
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

./deduplicate-assets.sh content public

echo "Сборка завершена"
