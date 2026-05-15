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
# 1. LOCAL MACROS
# =============================================================================

step "Writing local macros"

cat >/etc/exim4/conf.d/main/00_local_macros <<EOF
primary_hostname = ${PRIMARY_HOSTNAME}
daemon_smtp_ports = 25 : 587
DKIM_SELECTOR = ${DKIM_SELECTOR}
EOF

done_ok

# =============================================================================
# 2. TLS OPTIONS
# =============================================================================

step "Configuring TLS"

mkdir -p /etc/exim4/conf.d/main

cat >/etc/exim4/conf.d/main/01_tls_paths <<EOF
tls_certificate = ${TLS_CERT}
tls_privatekey = ${TLS_KEY}
tls_advertise_hosts = *
EOF

sed -i 's/^tls_certificate = MAIN_TLS_CERT/#tls_certificate = MAIN_TLS_CERT/' /etc/exim4/conf.d/main/03_exim4-config_tlsoptions

done_ok

# =============================================================================
# 3. LETSENCRYPT PERMISSIONS
# =============================================================================

step "Fixing certificate permissions"

chgrp -R "${EXIM_USER}" /etc/letsencrypt/live /etc/letsencrypt/archive
chmod 750 /etc/letsencrypt/live /etc/letsencrypt/archive

done_ok

# =============================================================================
# 4. STARTTLS ACL
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
# 5. SMTP AUTH
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
# 6. SMTP AUTH PASSWORD FILE
# =============================================================================

step "Creating SMTP password file"

if [ -n "${SMTP_AUTH_PASS}" ]; then
  HASHED_PASS=$(openssl passwd -6 "${SMTP_AUTH_PASS}")
  cat >/etc/exim4/passwd <<EOF
${SMTP_AUTH_USER}:${HASHED_PASS}
EOF
fi

if [ -f /etc/exim4/passwd ]; then
  chown root:${EXIM_USER} /etc/exim4/passwd
  chmod 640 /etc/exim4/passwd
fi

done_ok

# =============================================================================
# 7. DKIM KEYS
# =============================================================================

step "Generating DKIM keys"

mkdir -p "${DKIM_BASE}"

for domain in ${MAIL_DOMAINS}; do
  DOMAIN_DIR="${DKIM_BASE}/${domain}"
  mkdir -p "${DOMAIN_DIR}"

  PRIVATE_KEY="${DOMAIN_DIR}/mail.private"
  PUBLIC_KEY="${DOMAIN_DIR}/mail.public"

  if [ ! -f "${PRIVATE_KEY}" ]; then
    openssl genrsa -out "${PRIVATE_KEY}" 2048 >/dev/null 2>&1
    openssl rsa -in "${PRIVATE_KEY}" -pubout -out "${PUBLIC_KEY}" >/dev/null 2>&1
  fi

  PUBKEY=$(openssl rsa -in "${PRIVATE_KEY}" -pubout 2>/dev/null | grep -v "\-----" | tr -d '\n')

  cat >"${DOMAIN_DIR}/dns_record.txt" <<EOF
${DKIM_SELECTOR}._domainkey.${domain}. TXT "v=DKIM1; k=rsa; p=${PUBKEY}"
EOF

  chown -R "${EXIM_USER}" "${DOMAIN_DIR}"
  chmod 640 "${PRIVATE_KEY}"
  chmod 644 "${PUBLIC_KEY}"
done

done_ok

# =============================================================================
# 8. DKIM LOOKUP FILE
# =============================================================================

step "Writing DKIM lookup file"

>/etc/exim4/dkim_keys
for domain in ${MAIL_DOMAINS}; do
  echo "${domain}: ${DKIM_BASE}/${domain}/mail.private" >>/etc/exim4/dkim_keys
done

chown root:"${EXIM_USER}" /etc/exim4/dkim_keys
chmod 640 /etc/exim4/dkim_keys

done_ok

# =============================================================================
# 9. DKIM TRANSPORT
# =============================================================================

step "Creating DKIM transport"

cat >/etc/exim4/conf.d/transport/32_dkim_transport <<EOF
remote_smtp_dkim:
  driver = smtp
  dkim_domain = \${lookup{\$sender_address_domain}lsearch{/etc/exim4/dkim_keys}{\$sender_address_domain}{}}
  dkim_selector = DKIM_SELECTOR
  dkim_private_key = \${lookup{\$sender_address_domain}lsearch{/etc/exim4/dkim_keys}{\$value}{0}}
  dkim_canon = relaxed
EOF

done_ok

# =============================================================================
# 10. ROUTER PATCH
# =============================================================================

step "Patching primary router"

ROUTER_FILE="/etc/exim4/conf.d/router/200_exim4-config_primary"

if ! grep -q "transport = remote_smtp_dkim" "${ROUTER_FILE}"; then
  sed -i 's/transport = remote_smtp/transport = remote_smtp_dkim/g' "${ROUTER_FILE}"
fi

done_ok

# =============================================================================
# 11. CATCHALL FORWARD
# =============================================================================

step "Configuring catchall forwarding"

DOMAIN_LIST=$(echo "${MAIL_DOMAINS}" | tr ' ' ':')

cat >/etc/exim4/conf.d/router/850_exim4-config_catch_all_forward <<EOF
catch_all_forward:
  driver = redirect
  domains = ${DOMAIN_LIST}
  data = ${FORWARD_TO}
  unseen
  no_verify
EOF

done_ok

# =============================================================================
# 12. UPDATE-EXIM4.CONF.CONF
# =============================================================================

step "Updating update-exim4.conf.conf"

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
# 13. REBUILD AND VALIDATE
# =============================================================================

step "Rebuilding and validating Exim configuration"

update-exim4.conf || fail "update-exim4.conf failed"
exim -bV >/dev/null 2>&1 || fail "exim -bV failed"
exim -C /var/lib/exim4/config.autogenerated -bV >/dev/null 2>&1 || fail "exim autogenerated config validation failed"
exim -bP primary_hostname | grep -q "${PRIMARY_HOSTNAME}" || fail "primary_hostname validation failed"
exim -bP authenticators | grep -q "plain_server" || fail "authenticators validation failed"

done_ok

# =============================================================================
# 14. START EXIM
# =============================================================================

if [ "${SKIP_EXIM}" = "1" ]; then
  echo -e "${BLUE}  - SKIP_EXIM=1, skipping restart${NC}"
else
  step "Restarting Exim"
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart exim4 || fail "systemctl restart exim4 failed"
  else
    service exim4 restart || fail "service exim4 restart failed"
  fi
  done_ok
fi

# =============================================================================
# 15. PRINT DKIM DNS RECORDS
# =============================================================================

echo ""
echo -e "${GREEN}=== DKIM DNS RECORDS ===${NC}"

for domain in ${MAIL_DOMAINS}; do
  if [ -f "${DKIM_BASE}/${domain}/dns_record.txt" ]; then
    echo -e "${BLUE}${domain}:${NC}"
    cat "${DKIM_BASE}/${domain}/dns_record.txt"
    echo ""
  fi
done

echo -e "${GREEN}Configuration Complete.${NC}"
