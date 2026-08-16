# Copyright (c) 2026 RokctAI
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
import re
from compliance.base import register_file_checker

@register_file_checker
def check_layer10_clean_architecture(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    # Normalize separators: the directory-boundary tests below ("/components/",
    # "/presentation/", ...) silently never matched on Windows without this.
    path_lower = filepath.replace("\\", "/").lower()

    # Next.js Boundaries
    if path_lower.endswith(".ts") or path_lower.endswith(".tsx"):
        if "/components/" in path_lower:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                # DECISION: We allow bypassing checks intentionally if developers write bypass keywords in comments.
                # Here we parse for import targets strictly using regex to prevent false positives in comments/strings.
                has_drizzle_import = re.search(r'import\s+.*\s+from\s+[\'"]drizzle-orm[\'"]', content)
                has_prisma_import = re.search(r'import\s+.*\s+from\s+[\'"]prisma[\'"]', content)
                has_db_import = re.search(r'import\s+.*\s+from\s+[\'"]@/db[\'"]', content)
                
                if has_drizzle_import or has_prisma_import or has_db_import:
                    errors.append({
                        "line": 1,
                        "type": "Layer 10 (Clean Architecture - Next.js)",
                        "message": f"Presentational UI component '{os.path.basename(filepath)}' directly imports database clients or schemas. Delegate data access to Server Actions, API routes, or Services."
                    })
            except Exception as e:
                errors.append({"line": 1, "type": "Parse Error", "message": str(e)})

    # Flutter Boundaries
    elif path_lower.endswith(".dart"):
        if any(x in path_lower for x in ["/presentation/", "/pages/", "/widgets/"]):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # DECISION: We check for real import statements using strict regex rather than raw text substrings
                # to prevent documentations or code comments from triggering false positives.
                has_dio_import = re.search(r'import\s+[\'"]package:dio/.*[\'"]', content)
                has_http_import = re.search(r'import\s+[\'"]package:http/.*[\'"]', content)
                has_dio_instance = "Dio()." in content
                
                if has_dio_import or has_http_import or has_dio_instance:
                    errors.append({
                        "line": 1,
                        "type": "Layer 10 (Clean Architecture - Flutter)",
                        "message": f"Presentation Widget '{os.path.basename(filepath)}' initiates direct raw API/HTTP requests. Delegate networking to Repositories or State Providers."
                    })
                
                # Enforce: Presentation widgets should not import local DB libraries directly
                has_local_db_import = False
                for pkg in ["package:isar/", "package:hive/", "package:sqflite/", "package:drift/"]:
                    if f"import '{pkg}" in content or f'import "{pkg}' in content:
                        has_local_db_import = True
                        break
                        
                if has_local_db_import:
                    errors.append({
                        "line": 1,
                        "type": "Layer 10 (Clean Architecture - Flutter Local DB)",
                        "message": f"Presentation UI '{os.path.basename(filepath)}' directly imports a local database. Delegate storage queries to repositories or services."
                    })
                # Enforce: Presentation widgets should not do heavy serialization or MethodChannels (excluding bypass comments)
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
            # DECISION: Refined IP regex search to only match valid IPv4 octets between 0-255.
            # We also ensure the IP candidate isn't surrounded by dots or alphanumeric characters 
            # to verify it's not a software release version string (e.g. 1.2.3.4).
            ip_pattern = re.compile(
                r'(?<![0-9a-zA-Z\.])'  # Not preceded by digit, letter, or dot
                r'(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
                r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)'
                r'(?![0-9a-zA-Z\.])'  # Not followed by digit, letter, or dot
            )
            for idx, line in enumerate(lines, 1):
                if line.strip().startswith("#"):
                    continue
                # DECISION: Restrict scanning to actual variable assignments or configuration mappings rather than global line scraping.
                # This prevents false positives on release version strings (e.g. 1.2.3.4) inside documentation or configuration files.
                is_assignment = False
                if filepath.endswith((".yml", ".yaml")):
                    if ":" in line or line.strip().startswith("-"):
                        is_assignment = True
                elif filepath.endswith((".sh", ".bash")):
                    if "=" in line or any(cmd in line for cmd in ["export", "set", "env", "run", "curl", "wget", "ssh"]):
                        is_assignment = True
                
                if not is_assignment:
                    continue

                matches = ip_pattern.findall(line)
                for ip in matches:
                    try:
                        import ipaddress
                        ip_obj = ipaddress.ip_address(ip)
                        # DECISION: We utilize the standard library ipaddress module to discern local loopback, 
                        # private networks (e.g., 10.x.x.x, 172.16-31.x.x, 192.168.x.x), and unspecified/multicast IPs 
                        # from hardcoded production public infrastructure IP configurations, removing ad-hoc string comparisons.
                        if ip_obj.is_loopback or ip_obj.is_private or ip_obj.is_unspecified:
                            continue
                    except ValueError:
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
