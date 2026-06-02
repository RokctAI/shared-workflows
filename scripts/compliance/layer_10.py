import os
import re
from compliance.base import register_file_checker

@register_file_checker
def check_layer10_clean_architecture(filepath):
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
                # Enforce: Presentation widgets should not import local DB libraries directly
                if any(pkg in content for pkg in ["package:isar/", "package:hive/", "package:sqflite/", "package:drift/"]):
                    errors.append({
                        "line": 1,
                        "type": "Layer 10 (Clean Architecture - Flutter Local DB)",
                        "message": f"Presentation UI '{os.path.basename(filepath)}' directly imports a local database. Delegate storage queries to repositories or services."
                    })
                # Enforce: Presentation widgets should not do heavy serialization or MethodChannels
                if "MethodChannel(" in content or "jsonDecode(" in content or "jsonEncode(" in content:
                    errors.append({
                        "line": 1,
                        "type": "Layer 10 (Clean Architecture - Flutter Business Logic)",
                        "message": f"Presentation Widget '{os.path.basename(filepath)}' contains direct low-level MethodChannel or JSON serialization business logic. Delegate to BLoCs, Providers, or Controllers."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})
    return errors

@register_file_checker
def check_layer10_deployment_safety(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    if filepath.endswith(".sh") or filepath.endswith(".bash") or filepath.endswith(".yml") or filepath.endswith(".yaml"):
        if "production.env" in base or "compliance" in base:
            return errors
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
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

@register_file_checker
def check_layer10_localhost_decoupling(filepath):
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
