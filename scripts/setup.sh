#!/usr/bin/env sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
env_file="$project_root/.env"
odoo_config="$project_root/config/odoo.conf"

if [ ! -f "$env_file" ]; then
    cp "$project_root/.env.example" "$env_file"
    printf '%s\n' 'Created .env from the example template.'
else
    printf '%s\n' 'Kept the existing .env unchanged.'
fi

if [ ! -f "$odoo_config" ]; then
    cp "$project_root/config/odoo.conf.example" "$odoo_config"
    printf '%s\n' 'Created config/odoo.conf from the example template.'
else
    printf '%s\n' 'Kept the existing config/odoo.conf unchanged.'
fi

printf '%s\n' 'Before starting Docker, set the database password, Odoo master password, and licensed Enterprise addons path in these local files.'
