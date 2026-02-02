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

# Функция для обновления симлинка на хосте
update_host_symlink() {
    if [ -d "site" ]; then
        TARGET="$HOST_BACKUP_DIR"
        # Если путь относительный (не начинается с /), добавляем ../ т.к. линк лежит в site/
        if [[ "$HOST_BACKUP_DIR" != /* ]]; then
            # Убираем ./ в начале, если есть
            CLEAN_PATH=$(echo "$HOST_BACKUP_DIR" | sed 's|^\./||')
            TARGET="../$CLEAN_PATH"
        fi
        
        # Создаем/обновляем симлинк
        rm -f site/content
        ln -s "$TARGET" site/content
        echo "Обновлен симлинк: site/content -> $TARGET"
    fi
}

# Обновляем симлинк перед запуском
update_host_symlink

# Логика запуска
if [ "$1" == "build" ]; then
    echo "Сборка образов..."
    docker compose build

elif [ "$1" == "hugo" ]; then
    echo "Генерация сайта..."
    docker compose run --rm hugo

elif [ "$1" == "shell" ]; then
    echo "Запуск оболочки..."
    docker compose run --rm --entrypoint /bin/bash backup

else
    echo "Запуск бэкапа..."
    # Передаем все аргументы в скрипт backup
    docker compose run --rm backup "$@"
    
    echo "Генерация сайта..."
    docker compose run --rm hugo
fi
