#!/usr/bin/env python3
# Copyright 2026 RokctAI
# Compliance Scanner: Programmatically enforces production-grade quality across 5 layers:
# Layer 2 (API/Type Safety), Layer 3 (DB Migrations), Layer 4 & 5 (Security/Secrets Gate),
# Layer 6 (Rate Limiting), and Layer 12 (Observability).

import ast
import sys
import os
import subprocess

class PlatformComplianceVisitor(ast.NodeVisitor):
    def __init__(self, filename):
        self.filename = filename
        self.errors = []

    def visit_FunctionDef(self, node):
        # ==========================================
        # LAYER 12 & LAYER 2: WHITELISTED API ENDPOINTS
        # ==========================================
        is_whitelisted = False
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "whitelist":
                is_whitelisted = True
            elif isinstance(dec, ast.Attribute) and dec.attr == "whitelist":
                is_whitelisted = True
            elif isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Name) and func.id == "whitelist":
                    is_whitelisted = True
                elif isinstance(func, ast.Attribute) and func.attr == "whitelist":
                    is_whitelisted = True
        
        if is_whitelisted:
            # 1. Observability (Layer 12)
            has_trace_id = False
            has_stderr = False

            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Name) and subnode.id == "trace_id":
                    has_trace_id = True
                if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                    val_lower = subnode.value.lower()
                    if "x-trace-id" in val_lower or "x-request-id" in val_lower or "trace_id" in val_lower:
                        has_trace_id = True
                if isinstance(subnode, ast.Attribute) and subnode.attr == "stderr":
                    has_stderr = True
                if isinstance(subnode, ast.Name) and subnode.id == "stderr":
                    has_stderr = True

            if not has_trace_id or not has_stderr:
                missing = []
                if not has_trace_id:
                    missing.append("Layer 12: Trace ID propagation")
                if not has_stderr:
                    missing.append("Layer 12: sys.stderr structured logging")
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 12 (Observability)",
                    "message": f"whitelisted function '{node.name}()' lacks: {', '.join(missing)}"
                })

            # 2. Type-safety & Documentation (Layer 2)
            docstring = ast.get_docstring(node)
            if not docstring or not docstring.strip():
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 2 (API/Documentation)",
                    "message": f"whitelisted function '{node.name}()' must have a non-empty descriptive docstring."
                })

            # Verify parameter annotations
            for arg in node.args.args:
                if arg.arg in ["self", "cls"]:
                    continue
                if not arg.annotation:
                    self.errors.append({
                        "line": node.lineno,
                        "type": "Layer 2 (API/Type Safety)",
                        "message": f"whitelisted parameter '{arg.arg}' in '{node.name}()' lacks a type-hint annotation."
                    })

            # Verify return annotation
            if not node.returns:
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 2 (API/Type Safety)",
                    "message": f"whitelisted function '{node.name}()' lacks a return type-hint annotation (e.g. -> dict)."
                })

        # Continue traversing child nodes
        self.generic_visit(node)

    def visit_Call(self, node):
        # ==========================================
        # LAYER 3: DATABASE - SQL INJECTION PREVENTION
        # ==========================================
        is_db_sql = False
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "sql":
                if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "db":
                    if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "frappe":
                        is_db_sql = True
        
        if is_db_sql and len(node.args) > 0:
            sql_arg = node.args[0]
            is_unsafe = False
            # Check for f-strings: ast.JoinedStr
            if isinstance(sql_arg, ast.JoinedStr):
                is_unsafe = True
            # Check for % formatting
            elif isinstance(sql_arg, ast.BinOp) and isinstance(sql_arg.op, ast.Mod):
                is_unsafe = True
            # Check for .format() calls
            elif isinstance(sql_arg, ast.Call) and isinstance(sql_arg.func, ast.Attribute) and sql_arg.func.attr == "format":
                is_unsafe = True
            
            if is_unsafe:
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 3 (Database / SQL Injection)",
                    "message": "Unsafe raw SQL query detected. Avoid using f-strings, %, or .format() in frappe.db.sql(). Use parameterized inputs instead (e.g., frappe.db.sql('SELECT * FROM tabUser WHERE name = %s', user))."
                })

        # ==========================================
        # LAYER 15: OUTGOING HTTP REQUESTS MUST SPECIFY TIMEOUT
        # ==========================================
        is_http_call = False
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "requests":
                if node.func.attr in ["get", "post", "put", "delete", "patch", "request"]:
                    is_http_call = True
        
        if is_http_call:
            has_timeout = False
            for kw in node.keywords:
                if kw.arg == "timeout":
                    has_timeout = True
                    break
            if not has_timeout:
                self.errors.append({
                    "line": node.lineno,
                    "type": "Layer 15 (Webhook & Integration Federation)",
                    "message": f"Outgoing HTTP request 'requests.{node.func.attr}()' lacks a mandatory 'timeout' parameter to prevent hanging threads."
                })

        self.generic_visit(node)

    def visit_Assign(self, node):
        # ==========================================
        # LAYER 4 & 5: SECURITY - SECRET GATES
        # ==========================================
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id.lower()
                # Check for critical variable names
                if any(x in var_name for x in ["key", "token", "secret", "password"]):
                    # Ignore standard utility variables or loop parameters
                    if var_name in ["key", "keys", "token_usage", "cache_key", "secret_key_exists"]:
                        continue
                    # Check if value is a hardcoded string literal
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        val = node.value.value
                        # Ignore standard placeholder strings or safe empty variables
                        if val.strip() and val not in ["***", "placeholder", "default", "none", "", "travis"]:
                            self.errors.append({
                                "line": node.lineno,
                                "type": "Layer 4 & 5 (Security)",
                                "message": f"Hardcoded security parameter '{target.id}' assigned static value '{val[:15]}...'. Load credentials dynamically via os.environ or frappe.conf instead."
                            })

        self.generic_visit(node)

def check_nginx_rate_limiting(filepath):
    """
    LAYER 6: Rate Limiting validation for Nginx configurations or template managers.
    """
    errors = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # If the file defines an Nginx server or location block, verify it implements limit_req
        if "server {" in content or "location " in content:
            if "limit_req " not in content and "limit_req_zone" not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 6 (Rate Limiting)",
                    "message": f"Nginx server/location block config exposed in '{os.path.basename(filepath)}' without active 'limit_req' zone throttles."
                })
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_dockerfile_compliance(filepath):
    """
    LAYER 9: Enforces multi-stage builds inside Dockerfiles to guarantee optimized images.
    """
    errors = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if "FROM " in content:
            from_counts = content.count("FROM ")
            if from_counts < 2 and " AS " not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 9 (Containers)",
                    "message": f"Dockerfile '{os.path.basename(filepath)}' should utilize multi-stage builds ('FROM ... AS ...') to minimize final footprint."
                })
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_caching_and_cdn(filepath):
    """
    LAYER 7: Caching & CDN checks. Enforces caching headers or Next.js caching rules.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if "next.config" in base:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "headers" not in content and "cache-control" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 7 (Caching & CDN)",
                    "message": f"Next.js config file '{os.path.basename(filepath)}' lacks active CDN caching headers or 'headers()' configuration overrides."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    elif filepath.endswith(".conf") or "nginx" in filepath.lower():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "expires " not in content and "cache-control" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 7 (Caching & CDN)",
                    "message": f"Nginx config '{os.path.basename(filepath)}' does not configure static asset expiration rules or Cache-Control headers."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_load_balancing_and_scaling(filepath):
    """
    LAYER 8: Compose memory limits/scaling checks.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if ("docker-compose" in base or "compose" in base) and (base.endswith(".yml") or base.endswith(".yaml")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "mem_limit" not in content and "limits:" not in content and "memory:" not in content:
                errors.append({
                    "line": 1,
                    "type": "Layer 8 (Load Balancing & Scaling)",
                    "message": f"Docker Compose config '{os.path.basename(filepath)}' fails to specify container memory limits (mem_limit or deploy.resources.limits.memory) for resource isolation."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_availability_and_recovery(filepath):
    """
    LAYER 13: Availability & Backup test coverage.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if any(x in base for x in ["backup", "restore", "recovery"]) and any(filepath.endswith(ext) for ext in [".py", ".sh", ".ps1", ".bash"]):
        if "test" in base:
            return errors
        dir_name = os.path.dirname(filepath)
        test_filename_1 = "test_" + os.path.basename(filepath)
        test_filename_2 = os.path.basename(filepath).replace(".py", "_test.py").replace(".sh", "_test.sh").replace(".ps1", "_test.ps1").replace(".bash", "_test.bash")
        
        test_exists = False
        possible_dirs = [dir_name, os.path.join(dir_name, "tests"), os.path.join(dir_name, "test")]
        for d in possible_dirs:
            if os.path.exists(os.path.join(d, test_filename_1)) or os.path.exists(os.path.join(d, test_filename_2)):
                test_exists = True
                break
                
        if not test_exists:
            errors.append({
                "line": 1,
                "type": "Layer 13 (Availability & Backup)",
                "message": f"Backup/Recovery script '{os.path.basename(filepath)}' lacks a corresponding unit test file (e.g. '{test_filename_1}') in the codebase."
            })
    return errors

def check_nextjs_compliance(filepath):
    """
    LAYER 2, 4, 5, 7 Next.js Type Safety, Security, Caching checks.
    """
    errors = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        for idx, line in enumerate(lines, 1):
            # 1. Type Safety (Layer 2): Check for 'any' types
            if ": any" in line or " as any" in line or "<any>" in line:
                if not line.strip().startswith("//") and not line.strip().startswith("*"):
                    errors.append({
                        "line": idx,
                        "type": "Layer 2 (Type Safety - Next.js)",
                        "message": f"Bypassing type safety with 'any' type in '{os.path.basename(filepath)}'. Specify strong interfaces or concrete types."
                    })
            
            # 2. Secret Gate (Layer 4 & 5): Check for hardcoded credentials
            line_lower = line.lower()
            if any(k in line_lower for k in ["key", "secret", "token", "password"]):
                if ('"' in line or "'" in line) and not any(p in line_lower for p in ["process.env", "config", "placeholder", "import", "from"]):
                    parts = line.split("=")
                    if len(parts) > 1:
                        val = parts[1].strip()
                        if (val.startswith('"') or val.startswith("'")) and len(val) > 15:
                            errors.append({
                                "line": idx,
                                "type": "Layer 4 & 5 (Security - Next.js)",
                                "message": f"Hardcoded credential parameter detected in '{os.path.basename(filepath)}'. Use dynamic server env variables instead of static front-end strings."
                            })
                            
            # 3. Caching & CDN (Layer 7): API routes must configure revalidation or Cache-Control
            if "route.ts" in filepath.lower() or "route.js" in filepath.lower():
                content = "".join(lines)
                if "revalidate" not in content and "cache-control" not in content.lower() and "next:" not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 7 (Caching & CDN - Next.js)",
                        "message": f"API Route handler '{os.path.basename(filepath)}' lacks caching directives ('revalidate' parameter or Cache-Control headers) for CDN edge acceleration."
                    })
                    break
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_flutter_compliance(filepath):
    """
    LAYER 2, 4, 5, 12 Flutter Type Safety, Security, Observability checks.
    """
    errors = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        for idx, line in enumerate(lines, 1):
            # 1. Type Safety (Layer 2): Dynamic parameters
            if " dynamic " in line or "dynamic>" in line:
                if not line.strip().startswith("//") and not line.strip().startswith("*") and not line.strip().startswith("///"):
                    errors.append({
                        "line": idx,
                        "type": "Layer 2 (Type Safety - Flutter)",
                        "message": f"Avoid using raw 'dynamic' types in Flutter '{os.path.basename(filepath)}'. Define concrete Dart models or strong types."
                    })
                    
            # 2. Secret Gate (Layer 4 & 5): Hardcoded credentials in Dart
            line_lower = line.lower()
            if any(k in line_lower for k in ["key", "secret", "token", "password"]):
                if ('"' in line or "'" in line) and not any(p in line_lower for p in ["dotenv", "environment", "placeholder", "key:"]):
                    parts = line.split("=")
                    if len(parts) > 1:
                        val = parts[1].strip()
                        if (val.startswith('"') or val.startswith("'")) and len(val) > 15:
                            errors.append({
                                "line": idx,
                                "type": "Layer 4 & 5 (Security - Flutter)",
                                "message": f"Hardcoded constant credential detected in '{os.path.basename(filepath)}'. Inject variables dynamically via environment build arguments."
                            })
                            
            # 3. Observability (Layer 12): Propagate trace/request IDs in API operations
            if "api" in filepath.lower() or "service" in filepath.lower():
                content = "".join(lines)
                if "x-trace-id" not in content.lower() and "trace" not in content.lower() and "requestid" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 12 (Observability - Flutter)",
                        "message": f"Flutter API/Service layer '{os.path.basename(filepath)}' fails to propagate structured Trace/Request IDs in outgoing network header maps."
                    })
                    break
    except Exception as e:
        errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_architectural_boundaries(filepath):
    """
    LAYER 10: Clean Architecture & Layered Boundary Enforcement.
    Enforces strict separation of concerns for Next.js and Flutter.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()

    # Next.js Boundaries
    if path_lower.endswith(".ts") or path_lower.endswith(".tsx"):
        if "/components/" in path_lower:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Enforce: UI components should not query DB directly
                if "drizzle-orm" in content or "prisma" in content or "from \"@/db\"" in content or "from '@/db'" in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 10 (Clean Architecture - Next.js)",
                        "message": f"Presentational UI component '{os.path.basename(filepath)}' directly queries the database or schema. Delegate data access to Server Actions, API routes, or Services."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})

    # Flutter Boundaries
    elif path_lower.endswith(".dart"):
        if any(x in path_lower for x in ["/presentation/", "/pages/", "/widgets/"]):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # Enforce: Presentation widgets should not make raw HTTP/Dio API requests directly
                if "import 'package:dio/" in content or "import 'package:http/" in content or "Dio()." in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 10 (Clean Architecture - Flutter)",
                        "message": f"Presentation Widget '{os.path.basename(filepath)}' initiates direct raw API/HTTP requests. Delegate networking to Repositories or State Providers."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_layer5_nginx_headers(filepath):
    """
    LAYER 5: Network Security & Secure Headers enforcer.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if filepath.endswith(".conf") or "nginx" in filepath.lower():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "x-frame-options" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 5 (Security - Secure Headers)",
                    "message": f"Nginx config '{os.path.basename(filepath)}' lacks native 'X-Frame-Options' header injection to prevent Clickjacking attacks."
                })
            if "x-content-type-options" not in content.lower():
                errors.append({
                    "line": 1,
                    "type": "Layer 5 (Security - Secure Headers)",
                    "message": f"Nginx config '{os.path.basename(filepath)}' lacks native 'X-Content-Type-Options' sniff protection header."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_layer10_deployment_safety(filepath):
    """
    LAYER 10: Hosting & Deployment - Prevent hardcoded plain IPs and secrets in deployment scripts.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if filepath.endswith(".sh") or filepath.endswith(".bash") or filepath.endswith(".yml") or filepath.endswith(".yaml"):
        if "production.env" in base or "compliance" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            import re
            ip_pattern = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
            for idx, line in enumerate(lines, 1):
                if line.strip().startswith("#"):
                    continue
                matches = ip_pattern.findall(line)
                for ip in matches:
                    if ip in ["127.0.0.1", "0.0.0.0", "172.17.0.1"] or ip.startswith("10.6") or ip.startswith("3.14") or ip.startswith("2.4"):
                        continue
                    errors.append({
                        "line": idx,
                        "type": "Layer 10 (Hosting & Deployment Safety)",
                        "message": f"Hardcoded IP address literal '{ip}' detected in '{os.path.basename(filepath)}'. Parameterize deployments via environment variables."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_layer13_volume_persistence(filepath):
    """
    LAYER 13: Availability & Volume Persistence checks for Compose definitions.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    if ("docker-compose" in base or "compose" in base) and (base.endswith(".yml") or base.endswith(".yaml")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            if "db:" in content or "postgres" in content or "mariadb" in content:
                if "volumes:" not in content or "/var/lib/" not in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 13 (Availability & Backup)",
                        "message": f"Docker Compose configuration '{os.path.basename(filepath)}' runs a database service but lacks active persistent volume storage mounts."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_layer16_tenant_isolation(filepath):
    """
    LAYER 16: Multi-Tenant Boundaries & Quota Isolation Gate.
    Enforces strict tenant isolation and usage quotas in backend code.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if filepath.endswith(".py"):
        if not any(x in path_lower for x in ["rcore", "paas", "rpanel"]):
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 1. Tenant DB Query Isolation Check
            if any(q in content for q in ["frappe.db.get_list", "frappe.db.get_all", "frappe.get_all", "frappe.get_list", "frappe.get_doc"]):
                if "tenant" not in content.lower() and "session.user" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 16 (Multi-Tenant Isolation Gate)",
                        "message": f"Tenant database queries detected in '{os.path.basename(filepath)}' but no tenant context filters (tenant_id, tenant, or session.user) are active. Restrict queries to ensure complete data isolation."
                    })
            
            # 2. Free-Tier Quota Gate
            if "chat" in base or "completions" in base or "llm_service" in base:
                if "free_rok_msg_count" not in content and "quota" not in content.lower() and "limit" not in content.lower():
                    errors.append({
                        "line": 1,
                        "type": "Layer 16 (Quota Isolation Gate)",
                        "message": f"AI completion service '{os.path.basename(filepath)}' is missing active usage quota limit checks (e.g. checking 'free_rok_msg_count' Redis usage counters)."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_layer10_localhost_decoupling(filepath):
    """
    LAYER 10: Localhost Decoupling Gate.
    Ensures that containers interact with each other as if they are remote spoke VPS nodes.
    Blocks hardcoded localhost/127.0.0.1 in Next.js, Flutter, and environment templates.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if filepath.endswith(".ts") or filepath.endswith(".tsx") or filepath.endswith(".dart") or filepath.endswith(".env") or filepath.endswith(".env.production") or filepath.endswith(".env.development"):
        if any(x in base for x in ["db", "postgres", "redis", "compliance", "seed"]):
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for idx, line in enumerate(lines, 1):
                if line.strip().startswith("//") or line.strip().startswith("#") or line.strip().startswith("///") or line.strip().startswith("*"):
                    continue
                line_lower = line.lower()
                if "localhost:" in line_lower or "127.0.0.1:" in line_lower or "http://localhost" in line_lower or "https://localhost" in line_lower:
                    errors.append({
                        "line": idx,
                        "type": "Layer 10 (Localhost Decoupling Gate)",
                        "message": f"Hardcoded local loopback address '{line.strip()[:30]}' detected in '{os.path.basename(filepath)}'. Use dynamic environment variables to support transparent local/remote spokes orchestration."
                    })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def check_layer15_webhook_federation(filepath):
    """
    LAYER 15: Webhook & Integration Federation.
    Ensures webhook integration handlers implement robust payload signature/HMAC verification.
    """
    errors = []
    base = os.path.basename(filepath).lower()
    path_lower = filepath.lower()
    if "webhook" in base or "webhook" in path_lower:
        if any(x in base for x in ["test", "fixture", "json", "yaml", "yml", "md", "txt"]):
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            required_sigs = ["signature", "hmac", "sha256", "verification", "x-hub-signature", "x-signature", "verify_signature", "verify"]
            if not any(sig in content.lower() for sig in required_sigs):
                errors.append({
                    "line": 1,
                    "type": "Layer 15 (Webhook Federation)",
                    "message": f"Webhook handler file '{os.path.basename(filepath)}' does not implement payload signature, HMAC verification, or secret verification hashes to prevent unauthorized spoofing."
                })
        except Exception as e:
            errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

def scan_file(filepath):
    errors = []
    if filepath.endswith(".py"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            tree = ast.parse(source, filepath)
            visitor = PlatformComplianceVisitor(filepath)
            visitor.visit(tree)
            errors.extend(visitor.errors)
        except Exception as e:
            errors.append({"line": 1, "type": "Syntax Error", "message": str(e)})

    # Run Next.js validations
    if filepath.endswith(".ts") or filepath.endswith(".tsx"):
        nextjs_errs = check_nextjs_compliance(filepath)
        errors.extend(nextjs_errs)

    # Run Flutter validations
    if filepath.endswith(".dart"):
        flutter_errs = check_flutter_compliance(filepath)
        errors.extend(flutter_errs)

    # Run Nginx rate-limiting validations
    if "nginx" in filepath.lower() or filepath.endswith(".conf"):
        nginx_errs = check_nginx_rate_limiting(filepath)
        errors.extend(nginx_errs)

    # Run Dockerfile validations
    if "dockerfile" in filepath.lower():
        dockerfile_errs = check_dockerfile_compliance(filepath)
        errors.extend(dockerfile_errs)

    # Run Caching & CDN checks
    cdn_errs = check_caching_and_cdn(filepath)
    errors.extend(cdn_errs)

    # Run Load Balancing checks
    scaling_errs = check_load_balancing_and_scaling(filepath)
    errors.extend(scaling_errs)

    # Run Backup checks
    backup_errs = check_availability_and_recovery(filepath)
    errors.extend(backup_errs)

    # Run Architectural Boundary checks
    arch_errs = check_architectural_boundaries(filepath)
    errors.extend(arch_errs)

    # Run Layer 5 Nginx header checks
    nginx_header_errs = check_layer5_nginx_headers(filepath)
    errors.extend(nginx_header_errs)

    # Run Layer 10 Plain IP checks
    ip_safety_errs = check_layer10_deployment_safety(filepath)
    errors.extend(ip_safety_errs)

    # Run Layer 13 Volume Persistence checks
    volume_persistence_errs = check_layer13_volume_persistence(filepath)
    errors.extend(volume_persistence_errs)

    # Run Layer 10 Localhost Decoupling Gate checks
    localhost_decoupling_errs = check_layer10_localhost_decoupling(filepath)
    errors.extend(localhost_decoupling_errs)

    # Run Layer 15 Webhook Federation & Integration Federation checks
    webhook_federation_errs = check_layer15_webhook_federation(filepath)
    errors.extend(webhook_federation_errs)

    # Run Layer 16 Multi-Tenant & Quota Boundary checks
    tenant_isolation_errs = check_layer16_tenant_isolation(filepath)
    errors.extend(tenant_isolation_errs)

    return errors

def check_database_migrations(changed_files):
    """
    LAYER 3: Verify that structural DocType changes are accompanied by DB migration patch files.
    """
    errors = []
    doctype_changed = False
    patch_changed = False

    for file in changed_files:
        if "doctype" in file and file.endswith(".json"):
            doctype_changed = True
        if "patches" in file or "migrations" in file or "patch" in file.lower():
            patch_changed = True

    if doctype_changed and not patch_changed:
        errors.append({
            "line": 1,
            "type": "Layer 3 (Database Integrity)",
            "message": "DocType schema JSON metadata files were modified, but no database migration scripts (under patches/ or migrations/) were found to handle state migration."
        })
    return errors

def main():
    print("=" * 80)
    print("ROKCT PLATFORM ECOSYSTEM - ARCHITECTURAL COMPLIANCE GATEWAY")
    print("=" * 80)

    # 1. Resolve files to scan: either passed directly or changed in git diff
    files_to_scan = []
    changed_files_list = []
    
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if os.path.isfile(arg):
                files_to_scan.append(arg)
                changed_files_list.append(arg)
            elif os.path.isdir(arg):
                for root, dirs, files in os.walk(arg):
                    # Prune third-party dependency, build, and platform cache directories
                    dirs[:] = [d for d in dirs if d not in [".git", "node_modules", ".next", "dist", ".dart_tool", "build", "ios", "android", "env", "__pycache__"]]
                    for file in files:
                        fp = os.path.join(root, file)
                        if file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower():
                            files_to_scan.append(fp)
                            changed_files_list.append(fp)
    else:
        # Default: scan recursively from current directory to force strict codebase-wide compliance
        print("Scanning all python/config/nextjs/flutter files in current workspace for full compliance...")
        for root, dirs, files in os.walk("."):
            # Prune third-party and platform build cache folders
            dirs[:] = [d for d in dirs if d not in [".git", "env", "node_modules", "__pycache__", ".shared-workflows", ".next", "dist", ".dart_tool", "build", "ios", "android"]]
            for file in files:
                fp = os.path.join(root, file)
                if file.endswith(".py") or file.endswith(".ts") or file.endswith(".tsx") or file.endswith(".dart") or "nginx" in file.lower() or file.endswith(".conf") or file.endswith(".yml") or file.endswith(".yaml") or "dockerfile" in file.lower():
                    files_to_scan.append(fp)
                if file.endswith(".json") and "doctype" in fp:
                    changed_files_list.append(fp)

    if not files_to_scan and not changed_files_list:
        print("SUCCESS: No source files resolved for scan. Exiting.")
        sys.exit(0)

    print(f"Auditing {len(files_to_scan)} source files...")
    total_violations = 0

    # 2. Run AST File Scanning
    for filepath in files_to_scan:
        errors = scan_file(filepath)
        if errors:
            print(f"\nCOMPLIANCE VIOLATION in: {filepath}")
            for err in errors:
                print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
                total_violations += 1

    # 3. Run Layer 3 Schema Compliance Checks
    migration_errors = check_database_migrations(changed_files_list)
    if migration_errors:
        print("\nCOMPLIANCE VIOLATION in: Git Schema Diff")
        for err in migration_errors:
            print(f"  [Line {err['line']}] [{err['type']}] -> {err['message']}")
            total_violations += 1

    print("\n" + "=" * 80)
    if total_violations > 0:
        print(f"ARCHITECTURAL COMPLIANCE FAILED: {total_violations} violations found.")
        print("All changes must adhere to ROKCT production-grade standards before merging.")
        print("=" * 80)
        sys.exit(1)
    else:
        print("ARCHITECTURAL COMPLIANCE SUCCESS: All systems pass production standards.")
        print("=" * 80)
        sys.exit(0)

if __name__ == "__main__":
    main()
