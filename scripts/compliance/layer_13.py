import os
from compliance.base import register_file_checker

@register_file_checker
def check_layer13_backup_recovery(filepath):
    errors = []
    base = os.path.basename(filepath).lower()
    if any(x in base for x in ["backup", "restore", "recovery"]) and any(filepath.endswith(ext) for ext in [".py", ".sh", ".ps1", ".bash"]):
        if "test" in base:
            return errors
        dir_name = os.path.dirname(filepath)
        test_filename_1 = "test_" + os.path.basename(filepath)
        test_filename_2 = os.path.basename(filepath).replace(".py", "_test.py").replace(".sh", "_test.sh").replace(".ps1", "_test.ps1").replace(".bash", "_test.bash")
        
        # DECISION: We look for the workspace root to support global tests/ folders (reducing false positives
        # when integration tests are organized separate from scripts). We walk upwards to find a repository boundary.
        workspace_root = dir_name
        curr = os.path.abspath(dir_name)
        while True:
            if os.path.exists(os.path.join(curr, ".git")) or os.path.exists(os.path.join(curr, ".rokct")):
                workspace_root = curr
                break
            parent = os.path.dirname(curr)
            if parent == curr: # Root reached
                break
            curr = parent
            
        test_exists = False
        
        # 1. Search locally/siblings
        possible_dirs = [dir_name, os.path.join(dir_name, "tests"), os.path.join(dir_name, "test")]
        for d in possible_dirs:
            if os.path.exists(os.path.join(d, test_filename_1)) or os.path.exists(os.path.join(d, test_filename_2)):
                test_exists = True
                break
                
        # 2. Walk globally from workspace root to find tests if not resolved locally
        if not test_exists:
            # DECISION: Match variations of the script name (e.g. "test_backup.py" or "backup_test.py")
            # globally to reduce false positives for E2E and consolidated test frameworks.
            base_no_ext = os.path.splitext(os.path.basename(filepath))[0]
            for root, dirs, files in os.walk(workspace_root):
                # Filter out obvious ignore directories to keep search speed fast
                dirs[:] = [d for d in dirs if d not in [".git", "node_modules", ".next", "dist", "build", "env", "__pycache__"]]
                for file in files:
                    if file == test_filename_1 or file == test_filename_2:
                        test_exists = True
                        break
                    file_lower = file.lower()
                    if base_no_ext in file_lower and "test" in file_lower:
                        test_exists = True
                        break
                if test_exists:
                    break
                    
        if not test_exists:
            errors.append({
                "line": 1,
                "type": "Layer 13 (Availability & Backup)",
                "message": f"Backup/Recovery script '{os.path.basename(filepath)}' lacks a corresponding unit test file (e.g. '{test_filename_1}') anywhere in the workspace."
            })
    return errors

@register_file_checker
def check_layer13_volume_persistence(filepath):
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
