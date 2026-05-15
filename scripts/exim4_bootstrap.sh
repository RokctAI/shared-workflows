#!/bin/bash
# =============================================================================
# RokctAI - Exim4 Bootstrap Configuration
# Safe fresh-VPS bootstrap for Exim4
# =============================================================================

set -Eeuo pipefail

# =============================================================================
# COLORS
# =============================================================================

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

step() { printf "${BLUE}  - %s... ${NC}" "$1"; }
done_ok() { echo -e "${GREEN}✓ DONE${NC}"; }
fail() {
  echo -e "${RED}✗ FAILED: $1${NC}"
  exit 1
}

# =============================================================================
# ENVIRONMENT VARIABLES
# =============================================================================

PRIMARY_HOSTNAME="${PRIMARY_HOSTNAME:-mail.juvo.app}"

MAIL_DOMAINS="${MAIL_DOMAINS:-juvo.app rokct.ai}"

FORWARD_TO="${FORWARD_TO:-sinyage@gmail.com}"

TLS_CERT="${TLS_CERT:-/etc/letsencrypt/live/${PRIMARY_HOSTNAME}/fullchain.pem}"
TLS_KEY="${TLS_KEY:-/etc/letsencrypt/live/${PRIMARY_HOSTNAME}/privkey.pem}"

DKIM_BASE="${DKIM_BASE:-/etc/exim4/dkim}"
DKIM_SELECTOR="${DKIM_SELECTOR:-dkim}"

SMTP_AUTH_USER="${SMTP_AUTH_USER:-hello@juvo.app}"
SMTP_AUTH_PASS="${SMTP_AUTH_PASS:-}"

EXIM_USER="${EXIM_USER:-Debian-exim}"

SKIP_EXIM="${SKIP_EXIM:-0}"

# =============================================================================
# PRECHECKS
# =============================================================================

echo -e "${GREEN}=== RokctAI Exim4 Bootstrap ===${NC}"

step "Checking Exim installation"

command -v exim4 >/dev/null 2>&1 || fail "exim4 not installed"

done_ok

step "Checking split-config mode"

grep -q "dc_use_split_config='true'" /etc/exim4/update-exim4.conf.conf ||
  fail "split config mode is not enabled"

done_ok

# =============================================================================
# LOCAL MACROS
# =============================================================================

step "Writing local macros"

cat >/etc/exim4/conf.d/main/00_local_macros <<EOF
primary_hostname = ${PRIMARY_HOSTNAME}

daemon_smtp_ports = 25 : 587

MAIN_TLS_ENABLE = yes
MAIN_TLS_CERTIFICATE = ${TLS_CERT}
MAIN_TLS_PRIVATEKEY = ${TLS_KEY}
MAIN_TLS_ADVERTISE_HOSTS = *

DKIM_SELECTOR = ${DKIM_SELECTOR}
EOF

done_ok

# =============================================================================
# TLS OPTIONS
# =============================================================================

step "Configuring TLS"

mkdir -p /etc/exim4/conf.d/main

cat >/etc/exim4/conf.d/main/01_tls_paths <<EOF
tls_certificate = ${TLS_CERT}
tls_privatekey = ${TLS_KEY}
tls_advertise_hosts = *
EOF

done_ok

# =============================================================================
# LETSENCRYPT PERMISSIONS
# =============================================================================

step "Fixing certificate permissions"

if [ -d /etc/letsencrypt/live ]; then

  chgrp -R "${EXIM_USER}" /etc/letsencrypt/live || true
  chgrp -R "${EXIM_USER}" /etc/letsencrypt/archive || true

  chmod 750 /etc/letsencrypt/live || true
  chmod 750 /etc/letsencrypt/archive || true
fi

done_ok

# =============================================================================
# STARTTLS ACL
# =============================================================================

step "Configuring STARTTLS ACL"

cat >/etc/exim4/conf.d/main/01_starttls_acl <<'EOF'
acl_smtp_starttls = acl_check_starttls
EOF

cat >/etc/exim4/conf.d/acl/30_exim4-config_starttls <<'EOF'
acl_check_starttls:
  accept
EOF

done_ok

# =============================================================================
# SMTP AUTH
# =============================================================================

step "Configuring SMTP AUTH"

cat >/etc/exim4/conf.d/auth/10_server_auth <<'EOF'
plain_server:
  driver = plaintext
  public_name = PLAIN
  server_prompts = :
  server_condition = ${if crypteq{$auth3}{${extract{2}{:}{${lookup{$auth2}lsearch{/etc/exim4/passwd}{$value}fail}}}}{yes}{no}}
  server_set_id = $auth2
  server_advertise_condition = ${if def:tls_in_cipher}

login_server:
  driver = plaintext
  public_name = LOGIN
  server_prompts = Username:: : Password::
  server_condition = ${if crypteq{$auth2}{${extract{2}{:}{${lookup{$auth1}lsearch{/etc/exim4/passwd}{$value}fail}}}}{yes}{no}}
  server_set_id = $auth1
  server_advertise_condition = ${if def:tls_in_cipher}
EOF

done_ok

# =============================================================================
# SMTP AUTH PASSWORD FILE
# =============================================================================

step "Creating SMTP password file"

touch /etc/exim4/passwd

if [ -n "${SMTP_AUTH_PASS}" ]; then

  HASHED_PASS=$(openssl passwd -6 "${SMTP_AUTH_PASS}")

  cat >/etc/exim4/passwd <<EOF
${SMTP_AUTH_USER}:${HASHED_PASS}
EOF

fi

chown root:${EXIM_USER} /etc/exim4/passwd
chmod 640 /etc/exim4/passwd

done_ok

# =============================================================================
# DKIM SETUP
# =============================================================================

step "Configuring DKIM"

mkdir -p "${DKIM_BASE}"

>/etc/exim4/dkim_keys

for domain in ${MAIL_DOMAINS}; do

  DOMAIN_DIR="${DKIM_BASE}/${domain}"

  mkdir -p "${DOMAIN_DIR}"

  PRIVATE_KEY="${DOMAIN_DIR}/mail.private"
  PUBLIC_KEY="${DOMAIN_DIR}/mail.public"

  if [ ! -f "${PRIVATE_KEY}" ]; then

    echo "Generating DKIM key for ${domain}"

    openssl genrsa -out "${PRIVATE_KEY}" 2048 >/dev/null 2>&1

    openssl rsa \
      -in "${PRIVATE_KEY}" \
      -pubout \
      -out "${PUBLIC_KEY}" >/dev/null 2>&1

  fi

  PUBKEY=$(openssl rsa -in "${PRIVATE_KEY}" -pubout 2>/dev/null |
    grep -v "-----" |
    tr -d '\n')

  cat >"${DOMAIN_DIR}/dns_record.txt" <<EOF
${DKIM_SELECTOR}._domainkey.${domain}. TXT "v=DKIM1; k=rsa; p=${PUBKEY}"
EOF

  echo "${domain}: ${PRIVATE_KEY}" >>/etc/exim4/dkim_keys

  chown -R ${EXIM_USER}:${EXIM_USER} "${DOMAIN_DIR}"

  chmod 640 "${PRIVATE_KEY}"
  chmod 644 "${PUBLIC_KEY}"

done

chown root:${EXIM_USER} /etc/exim4/dkim_keys
chmod 640 /etc/exim4/dkim_keys

done_ok

# =============================================================================
# DKIM TRANSPORT
# =============================================================================

step "Creating DKIM transport"

cat >/etc/exim4/conf.d/transport/32_dkim_transport <<'EOF'
remote_smtp_dkim:
  driver = smtp
  dkim_domain = ${lookup{$sender_address_domain}lsearch{/etc/exim4/dkim_keys}{$sender_address_domain}{}}
  dkim_selector = DKIM_SELECTOR
  dkim_private_key = ${lookup{$sender_address_domain}lsearch{/etc/exim4/dkim_keys}{$value}{0}}
  dkim_canon = relaxed
EOF

done_ok

# =============================================================================
# ROUTER PATCH
# =============================================================================

step "Patching primary router"

ROUTER_FILE="/etc/exim4/conf.d/router/200_exim4-config_primary"

if grep -q "transport = remote_smtp$" "${ROUTER_FILE}"; then

  sed -i \
    's/transport = remote_smtp$/transport = remote_smtp_dkim/g' \
    "${ROUTER_FILE}"

fi

done_ok

# =============================================================================
# CATCHALL FORWARD
# =============================================================================

step "Configuring catchall forwarding"

DOMAIN_LIST=$(echo "${MAIL_DOMAINS}" | tr ' ' ':')

cat >/etc/exim4/conf.d/router/150_exim4-config_catch_all_forward <<EOF
catch_all_forward:
  driver = redirect
  domains = ${DOMAIN_LIST}
  data = ${FORWARD_TO}
  unseen
  no_verify
EOF

done_ok

# =============================================================================
# UPDATE-EXIM4 CONFIG
# =============================================================================

step "Updating Exim config variables"

OTHER_HOSTNAMES=$(echo "${MAIL_DOMAINS}" | tr ' ' ':')
OTHER_HOSTNAMES="${PRIMARY_HOSTNAME}:${OTHER_HOSTNAMES}"

cat >/etc/exim4/update-exim4.conf.conf <<EOF
dc_eximconfig_configtype='internet'
dc_other_hostnames='${OTHER_HOSTNAMES}'
dc_local_interfaces='0.0.0.0 ; ::0'
dc_readhost=''
dc_relay_domains=''
dc_minimaldns='false'
dc_relay_nets=''
dc_smarthost=''
CFILEMODE='644'
dc_use_split_config='true'
dc_hide_mailname=''
dc_mailname_in_oh='true'
dc_localdelivery='mail_spool'
EOF

done_ok

# =============================================================================
# REBUILD CONFIG
# =============================================================================

step "Rebuilding Exim configuration"

update-exim4.conf || fail "update-exim4.conf failed"

done_ok

# =============================================================================
# VALIDATION
# =============================================================================

step "Validating Exim configuration"

exim -bV >/dev/null 2>&1 ||
  fail "exim config validation failed"

exim -bP primary_hostname >/dev/null 2>&1 ||
  fail "exim runtime config invalid"

done_ok

# =============================================================================
# START EXIM
# =============================================================================

if [ "${SKIP_EXIM}" = "1" ]; then

  echo -e "${BLUE}  - SKIP_EXIM=1, skipping restart${NC}"

else

  step "Restarting Exim"

  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart exim4 ||
      fail "systemctl restart failed"
  else
    service exim4 restart ||
      fail "service restart failed"
  fi

  done_ok

fi

# =============================================================================
# SUMMARY
# =============================================================================

echo ""
echo -e "${GREEN}=== CONFIGURATION COMPLETE ===${NC}"

echo -e "${BLUE}Hostname:${NC} ${PRIMARY_HOSTNAME}"
echo -e "${BLUE}Domains:${NC} ${MAIL_DOMAINS}"
echo -e "${BLUE}Catchall:${NC} ${FORWARD_TO}"
echo -e "${BLUE}TLS Cert:${NC} ${TLS_CERT}"

echo ""
echo -e "${GREEN}=== DKIM DNS RECORDS ===${NC}"

for domain in ${MAIL_DOMAINS}; do

  echo ""
  echo -e "${BLUE}${domain}${NC}"

  cat "${DKIM_BASE}/${domain}/dns_record.txt"

done

echo ""
echo -e "${GREEN}Done.${NC}"
