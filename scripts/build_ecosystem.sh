#!/bin/bash
set -e

# ==============================================================================
# RokctAI: Golden Build Script (build_ecosystem.sh)
# Author: Antigravity
# Description: Authoritative script for Frappe platform initialization, 
#              app synchronization, and ecosystem compilation.
# ==============================================================================

echo "🚀 RokctAI: Starting Golden Build Process..."

# --- 1. Environment Detection & Variable Setup ---
# Required Variables (should be provided by CI or Docker):
# BOOTSTRAP (true/false)
# DB_TYPE (mariadb/postgres)
# DB_PW
# APP_NAME (optional, will try to detect)
# GITHUB_WORKSPACE (optional)

BOOTSTRAP=${BOOTSTRAP:-false}
DB_TYPE=${DB_TYPE:-postgres}
DB_PW=${DB_PW:-admin}
APP_NAME=${APP_NAME:-""}
PY_BIN=${PY_BIN:-python3}

# Detect if running in Docker
if [ -f /.dockerenv ]; then
    IS_DOCKER=true
    echo "📦 Environment: Docker detected."
else
    IS_DOCKER=false
    echo "☁️ Environment: Host/CI detected."
fi

# --- 2. Identity & Services ---
echo "RokctAI: Setting up Identity & Services..."

# git setup (CI only, Docker usually has its own or doesn't need tokens)
if [ "$IS_DOCKER" = "false" ] && [ -n "$GITHUB_TOKEN" ]; then
    git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "git@github.com:"
    git config --global url."https://x-access-token:${GITHUB_TOKEN}@github.com/".insteadOf "https://github.com/"
    echo "✅ Global Git config updated with token."
fi

# Redis Startup
if [ "$IS_DOCKER" = "false" ]; then
    echo "Starting Redis instances (Host/CI)..."
    if ! command -v redis-server > /dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq redis-server
    fi
    sudo redis-server --port 11000 --daemonize yes
    sudo redis-server --port 12000 --daemonize yes
    sudo redis-server --port 13000 --daemonize yes
    for port in 11000 12000 13000; do
       while ! nc -z localhost $port; do sleep 1; done
    done
    echo "✅ Redis instances ready."
else
    echo "Starting Redis Service (Docker)..."
    sudo service redis-server start || true
fi

# PostgreSQL Startup
if [ "$IS_DOCKER" = "false" ] && [ "$BOOTSTRAP" = "false" ]; then
    echo "Starting PostgreSQL Service (CI Docker DB)..."
    if ! docker ps -a | grep -q db-service; then
        docker run -d --name db-service -p 5432:5432 -e POSTGRES_PASSWORD=$DB_PW -e POSTGRES_USER=postgres pgvector/pgvector:pg15
    fi
    timeout 60s bash -c 'until docker exec db-service pg_isready -U postgres; do sleep 2; done'
    docker exec db-service psql -U postgres -d template1 -c "CREATE EXTENSION IF NOT EXISTS vector;"
    docker exec db-service psql -U postgres -d template1 -c "CREATE EXTENSION IF NOT EXISTS cube;"
    docker exec db-service psql -U postgres -d template1 -c "CREATE EXTENSION IF NOT EXISTS earthdistance;"
    echo "✅ PostgreSQL ready."
elif [ "$IS_DOCKER" = "true" ]; then
    echo "Starting PostgreSQL Service (Docker Native)..."
    sudo service postgresql start || true
    # Wait for postgres to be ready
    for i in {1..30}; do
        if pg_isready -q; then break; fi
        echo "Waiting for PostgreSQL..."
        sleep 2
    done
    sudo -u postgres psql -c "ALTER USER postgres PASSWORD '$DB_PW';" || true
    sudo -u postgres psql -d template1 -c "CREATE EXTENSION IF NOT EXISTS vector;" || true
    sudo -u postgres psql -d template1 -c "CREATE EXTENSION IF NOT EXISTS cube;" || true
    sudo -u postgres psql -d template1 -c "CREATE EXTENSION IF NOT EXISTS earthdistance;" || true
fi

# --- 3. Bench Initialization ---
echo "RokctAI: Bench Initialization..."

if [ "$BOOTSTRAP" = "false" ]; then
    if [ ! -d "frappe-bench" ]; then
        pip install frappe-bench
        bench init --skip-redis-config-generation --skip-assets --python $PY_BIN frappe-bench
    fi
else
    # Bootstrap path (install.sh)
    if [ ! -f "install.sh" ]; then
        wget https://raw.githubusercontent.com/RokctAI/rPanel/main/install.sh
        chmod +x install.sh
    fi
    sudo CI=true DB_TYPE=$DB_TYPE ./install.sh
    
    if [ -d "/home/frappe/frappe-bench" ]; then
        [ -d "frappe-bench" ] && [ ! -L "frappe-bench" ] && rm -rf frappe-bench
        sudo ln -sf /home/frappe/frappe-bench ./frappe-bench
        sudo chown -R $USER:$USER /home/frappe/frappe-bench
    fi
fi

# --- 4. Workspace Sync & Mandatory Hacks ---
echo "RokctAI: Applying Mandatory Hacks & Sync..."

cd frappe-bench
if [ -f "env/bin/activate" ]; then source env/bin/activate; fi

# Detect App Name if not provided
if [ -z "$APP_NAME" ]; then
    # Try to find an app that isn't standard
    APP_NAME=$(find apps -maxdepth 1 -type d ! -name "apps" ! -name "frappe" ! -name "erpnext" ! -name "payments" -printf "%f\n" | head -n 1)
    APP_NAME=${APP_NAME:-"rpanel"} # fallback
fi

echo "Target App Detected: $APP_NAME"

# Renaming Hack (if folder doesn't match naming convention)
# Actually, the nuclear aliasing usually handles this better.

# 2. Generalized Module Aliasing (Nuclear Strategy)
if [ -d "apps/$APP_NAME/$APP_NAME" ]; then
    ALIAS_NAME="frappe${APP_NAME}"
    PY_VER=$(env/bin/python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    S_PACKAGES="env/lib/python${PY_VER}/site-packages"
    
    if [ -d "$S_PACKAGES" ]; then
       echo "Injecting Nuclear Alias into site-packages: $ALIAS_NAME"
       ln -sf "$PWD/apps/$APP_NAME/$APP_NAME" "$S_PACKAGES/$ALIAS_NAME"
    fi
    
    # Internal app-level alias
    if [ ! -d "apps/$APP_NAME/$ALIAS_NAME" ]; then
       cd apps/$APP_NAME && ln -sf $APP_NAME $ALIAS_NAME && cd ../..
    fi
fi

# 3. Namespace Package Fix
find apps/$APP_NAME/$APP_NAME -type d | while read dir; do
    if [ ! -f "$dir/__init__.py" ]; then touch "$dir/__init__.py"; fi
done

# 4. API Deprecation Patch
if [ -d "apps/$APP_NAME" ]; then
    grep -r "frappe.utils.update_site_config" apps/$APP_NAME | cut -d: -f1 | sort | uniq | xargs -r sed -i 's/frappe.utils.update_site_config/frappe.installer.update_site_config/g' || true
fi

# 5. Forced App Registration
echo "Registering $APP_NAME in editable mode..."
bench pip install -e "apps/$APP_NAME"

# --- 5. Ecosystem Compilation ---
echo "RokctAI: Compiling Ecosystem..."

# Map platform host
echo "127.0.0.1 platform.rokct.ai" | sudo tee -a /etc/hosts

# Site Setup
if [ "$BOOTSTRAP" = "false" ]; then
    SITE_NAME="platform.rokct.ai"
    if [ "$DB_TYPE" = "mariadb" ]; then
        bench new-site $SITE_NAME --db-root-password $DB_PW --admin-password admin --no-mariadb-socket || true
    else
        bench new-site $SITE_NAME --db-type postgres --db-root-password $DB_PW --admin-password admin || true
    fi
    echo "$SITE_NAME" > sites/currentsite.txt
    bench --site $SITE_NAME install-app $APP_NAME
else
    SITE_NAME=$(ls sites | grep .local | head -n 1)
    SITE_NAME=${SITE_NAME:-rpanel.local}
fi

# Final Migration
bench --site $SITE_NAME migrate

# RokctAI: Stack Installation (Control)
if [ -d "apps/control" ]; then
    echo "RokctAI: Running Stack Installer..."
    python3 apps/control/install_stack.py $SITE_NAME
    
    echo "RokctAI: Generating Golden DB Seed..."
    bench --site $SITE_NAME backup
    BACKUP_FILE=$(ls sites/$SITE_NAME/private/backups/*-database.sql.gz | head -n 1)
    if [ -f "$BACKUP_FILE" ]; then
        mkdir -p apps/seed_data
        cp "$BACKUP_FILE" "apps/seed_data/seed.sql.gz"
        echo "✅ Golden Seed created at apps/seed_data/seed.sql.gz"
    fi
fi

# Run Tests if explicitly requested (usually CI only)
if [ "$RUN_TESTS" = "true" ]; then
    echo "RokctAI: Running Tests for $APP_NAME..."
    bench --site $SITE_NAME run-tests --app $APP_NAME
fi

echo "✅ RokctAI: Golden Build Complete!"
