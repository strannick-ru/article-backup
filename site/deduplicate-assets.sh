#!/bin/bash
set -u

if [ "$#" -ne 2 ]; then
    echo "Использование: $0 OUTPUT_DIR PUBLIC_DIR" >&2
    exit 2
fi

SOURCE_ROOT=$1
PUBLIC_ROOT=$2

if [ ! -d "$SOURCE_ROOT" ] || [ ! -d "$PUBLIC_ROOT" ]; then
    echo "Каталог бэкапа или public не найден" >&2
    exit 2
fi

SOURCE_ROOT=$(cd -- "$SOURCE_ROOT" && pwd -P) || exit 2
PUBLIC_ROOT=$(cd -- "$PUBLIC_ROOT" && pwd -P) || exit 2

linked=0
skipped=0
saved_bytes=0

while IFS= read -r -d '' source_file; do
    relative=${source_file#"$SOURCE_ROOT"/}
    public_file="$PUBLIC_ROOT/$relative"

    if [ ! -f "$public_file" ] || [ -L "$public_file" ]; then
        skipped=$((skipped + 1))
        continue
    fi

    public_parent=$(cd -- "$(dirname -- "$public_file")" && pwd -P) || {
        skipped=$((skipped + 1))
        continue
    }
    case "$public_parent/" in
        "$PUBLIC_ROOT/"*) ;;
        *)
            skipped=$((skipped + 1))
            continue
            ;;
    esac

    if ! cmp -s -- "$source_file" "$public_file"; then
        skipped=$((skipped + 1))
        continue
    fi

    size=$(wc -c < "$public_file")
    temp_link="$public_parent/.hardlink-${$}-${RANDOM}"

    if ln -- "$source_file" "$temp_link"; then
        if mv -f -- "$temp_link" "$public_file"; then
            linked=$((linked + 1))
            saved_bytes=$((saved_bytes + size))
        else
            rm -f -- "$temp_link"
            skipped=$((skipped + 1))
        fi
    else
        rm -f -- "$temp_link"
        skipped=$((skipped + 1))
    fi
done < <(find "$SOURCE_ROOT" -type f -path '*/assets/*' -print0)

echo "Связано файлов: $linked"
echo "Пропущено файлов: $skipped"
echo "Сэкономлено байт: $saved_bytes"
