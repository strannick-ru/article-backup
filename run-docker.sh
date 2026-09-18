#!/bin/bash
set -e

# Функция для извлечения output_dir из конфига
get_output_dir() {
    if [ -f "config.yaml" ]; then
        # Ищем строку output_dir:, удаляем ключи, кавычки и комментарии
        grep "^output_dir:" config.yaml | sed 's/^output_dir:[[:space:]]*//' | sed 's/[[:space:]]*#.*//' | tr -d '"' | tr -d "'"
    fi
}

# Определяем директорию
CONFIG_DIR=$(get_output_dir)
export HOST_BACKUP_DIR=${CONFIG_DIR:-./backup}

# Обработка тильды (~) в пути
HOST_BACKUP_DIR="${HOST_BACKUP_DIR/#\~/$HOME}"

echo "Используется директория бэкапа: $HOST_BACKUP_DIR"

# Hugo игнорирует content, если это симлинк за пределы корня проекта, и молча
# собирает пустой сайт. Docker резолвит цель bind-mount через такой симлинк и
# монтирует бэкап мимо /site/content. Поэтому нужен обычный каталог.
ensure_host_content_mountpoint() {
    if [ -d "site" ]; then
        if [ -L "site/content" ]; then
            rm -f site/content
            echo "Удалён симлинк site/content (мешает сборке Hugo)"
        fi

        mkdir -p site/content
        echo "Точка монтирования: site/content -> $HOST_BACKUP_DIR"
    fi
}

# Готовим точку монтирования перед запуском
ensure_host_content_mountpoint

# Hardlinks создаются на хосте: отдельные bind mounts внутри контейнера
# могут считаться разными файловыми системами.
deduplicate_public_assets() {
    if [ -d "$HOST_BACKUP_DIR" ] && [ -d "site/public" ]; then
        site/deduplicate-assets.sh "$HOST_BACKUP_DIR" "site/public"
    fi
}

# Логика запуска
if [ "$1" == "build" ]; then
    echo "Сборка образов..."
    docker compose build

elif [ "$1" == "hugo" ]; then
    echo "Генерация сайта..."
    docker compose run --rm hugo
    deduplicate_public_assets

elif [ "$1" == "shell" ]; then
    echo "Запуск оболочки..."
    docker compose run --rm --entrypoint /bin/bash backup

else
    echo "Запуск бэкапа..."
    # Передаем все аргументы в скрипт backup
    docker compose run --rm backup "$@"
    
    echo "Генерация сайта..."
    docker compose run --rm hugo
    deduplicate_public_assets
fi
