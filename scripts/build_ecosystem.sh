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

# --- 3. Bench Initialization & CLI Setup ---
echo "RokctAI: Bench Initialization & CLI Setup..."

# Ensure bench CLI is installed regardless of path
if ! command -v bench > /dev/null; then
    echo "Installing frappe-bench CLI..."
    $PY_BIN -m pip install --user frappe-bench || pip install --user frappe-bench
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ "$BOOTSTRAP" = "false" ]; then
    if [ ! -d "frappe-bench" ]; then
        bench init --skip-redis-config-generation --skip-assets --python $PY_BIN frappe-bench
    fi
else
    # Bootstrap path (install.sh)
    REPO_PATH=${GITHUB_REPOSITORY:-"RokctAI/rpanel"}
    REF_PATH=${GITHUB_REF_NAME:-"main"}
    
    echo "RokctAI: Ensuring clean install.sh from GitHub (${REPO_PATH}/${REF_PATH})..."
    rm -f install.sh
    wget -q https://raw.githubusercontent.com/${REPO_PATH}/${REF_PATH}/install.sh
    
    if [ ! -f "install.sh" ]; then
        echo "❌ Critical Error: Failed to download install.sh from ${REPO_PATH}/${REF_PATH}"
        exit 1
    fi
    chmod +x install.sh
    
    echo "Executing: sudo CI=true DB_TYPE=$DB_TYPE bash ./install.sh"
    sudo CI=true DB_TYPE=$DB_TYPE bash ./install.sh
    
    if [ -d "/home/frappe/frappe-bench" ]; then
        [ -d "frappe-bench" ] && [ ! -L "frappe-bench" ] && rm -rf frappe-bench
        sudo ln -sf /home/frappe/frappe-bench ./frappe-bench
        sudo chown -R $USER:$USER /home/frappe/frappe-bench
    fi
fi

# --- 4. Workspace Sync & Mandatory Hacks ---
echo "RokctAI: Applying Mandatory Hacks & Sync..."

# Ensure path is updated for current shell
export PATH="$HOME/.local/bin:$PATH"

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
    # Bootstrap path: rename site to platform.rokct.ai if it's not already
    ORIG_SITE=$(ls sites | grep .local | head -n 1)
    ORIG_SITE=${ORIG_SITE:-rpanel.local}
    SITE_NAME="platform.rokct.ai"
    if [ "$ORIG_SITE" != "$SITE_NAME" ] && [ -d "sites/$ORIG_SITE" ]; then
        echo "Renaming $ORIG_SITE to $SITE_NAME..."
        mv "sites/$ORIG_SITE" "sites/$SITE_NAME" || true
    fi
    echo "$SITE_NAME" > sites/currentsite.txt
fi

# 3. Standard Dependencies (ERPNext, Payments)
if [ "$INSTALL_PAYMENTS" = "true" ]; then
    echo "Installing Payments..."
    if [ ! -d "apps/payments" ]; then
        bench get-app payments --branch develop --resolve-deps --skip-assets || true
    fi
    bench --site $SITE_NAME install-app payments || true
fi

if [ "$INSTALL_ERPNEXT" = "true" ]; then
    echo "Installing ERPNext (version-16)..."
    if [ ! -d "apps/erpnext" ]; then
        bench get-app erpnext --branch version-16 --resolve-deps --skip-assets || true
    fi
    bench --site $SITE_NAME install-app erpnext || true
fi

# 4. Control App Installation (The Installer)
if [ -n "$GITHUB_WORKSPACE" ] && [ -d "$GITHUB_WORKSPACE/control" ]; then
    echo "🔥 Using LOCAL Control Panel from workspace..."
    mkdir -p apps/control
    cp -r "$GITHUB_WORKSPACE/control/." "apps/control/"
    bench pip install -e apps/control
elif [ ! -d "apps/control" ]; then
    echo "Installing Control Panel via HTTPS..."
    bench get-app https://x-access-token:${GITHUB_TOKEN}@github.com/RokctAI/control.git --resolve-deps --skip-assets
fi

# 5. Monorepo Overrides Staging & Application
if [ -n "$GITHUB_WORKSPACE" ] && [ -d "$GITHUB_WORKSPACE/monorepo_overrides" ]; then
    echo "Applying Monorepo Overrides..."
    # Bench Overrides
    if [ -d "$GITHUB_WORKSPACE/monorepo_overrides/bench" ]; then
        echo "Applying Bench Overrides..."
        # Try to find bench module path using pip show (more reliable than import for paths)
        ST_LIB=$(env/bin/python -m pip show frappe-bench 2>/dev/null | grep Location | cut -d' ' -f2 || echo "")
        [ -z "$ST_LIB" ] && ST_LIB=$(python3 -m pip show frappe-bench 2>/dev/null | grep Location | cut -d' ' -f2 || echo "")
        
        if [ -n "$ST_LIB" ] && [ -d "$ST_LIB/bench" ]; then
            BENCH_PATH="$ST_LIB/bench"
            echo "Found bench at $BENCH_PATH. Applying overrides..."
            cp -r "$GITHUB_WORKSPACE/monorepo_overrides/bench/bench/"* "$BENCH_PATH/" || true
        else
            echo "⚠️ Warning: 'bench' module path not found. Skipping bench overrides."
        fi
    fi
    # Control Overrides
    if [ -d "$GITHUB_WORKSPACE/monorepo_overrides/control" ]; then
        echo "Applying Control Overrides..."
        cp -rf "$GITHUB_WORKSPACE/monorepo_overrides/control/." "apps/control/"
    fi
fi

# 6. Ensure Stack Dependencies (Apps requested by install_stack.py)
echo "RokctAI: Checking ecosystem dependencies..."
for extra_app in lending rcore; do
    echo "Checking for $extra_app..."
    if [ ! -d "apps/$extra_app" ] || [ -z "$(ls -A apps/$extra_app 2>/dev/null)" ]; then
        if [ "$extra_app" = "lending" ]; then
             REPO_URL="https://github.com/frappe/lending.git"
             BRANCH="develop"
        else
             REPO_URL="https://github.com/RokctAI/${extra_app}.git"
             BRANCH="develop"
             [ -n "$GITHUB_TOKEN" ] && REPO_URL="https://x-access-token:${GITHUB_TOKEN}@github.com/RokctAI/${extra_app}.git"
        fi
        
        echo "RokctAI: Fetching $extra_app from $REPO_URL ($BRANCH)..."
        bench get-app "$REPO_URL" --branch "$BRANCH" --resolve-deps --skip-assets || \
        bench get-app "$REPO_URL" --resolve-deps --skip-assets || true
    else
        echo "✅ $extra_app already present."
    fi
done

echo "Current apps directory: $(ls apps)"

# Final Migration & App Installation
bench --site $SITE_NAME install-app control || true
bench --site $SITE_NAME migrate

# RokctAI: Stack Installation (Control)
if [ -d "apps/control" ] && [ -f "apps/control/install_stack.py" ]; then
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
