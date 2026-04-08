import re

filepath = '.github/workflows/universal-release.yml'
with open(filepath, 'r') as f:
    content = f.read()

# Pattern for the NEW_VER block
pattern = r'NEW_VER=\$\(python3 -c "import sys;.*?"\)'

import re

def to_single_line(match):
    block = match.group(0)
    # Extract the script part between " and "
    script_match = re.search(r'python3 -c "(.*?)"', block, re.DOTALL)
    if script_match:
        script = script_match.group(1)
        # Convert multi-line script to single line with semicolons
        # Note: this is a bit risky if there are already semicolons or complex structures
        # But for this specific script it should be fine if we're careful
        lines = [l.strip() for l in script.splitlines() if l.strip()]
        # join with ; but be careful about if/try blocks
        # Actually, let's just use the correctly indented version but make sure it has enough spaces
        return block # Fallback
    return block

# Let's try again with the indented version but use a literal replacement to be exact
# Based on previous cat -n output
old_fragment = """           NEW_VER=$(python3 -c "import sys; cur_ver = '$CUR_VER'; fmt_str = '$FORMAT'
           try:
           v_parts = [int(x) for x in cur_ver.split('.')]
           f_parts = fmt_str.split('.')
           v_parts[-1] += 1
           for i in range(len(v_parts)-1, 0, -1):
           width = f_parts[i].count('#')
           limit = 10**width
           if v_parts[i] >= limit:
           v_parts[i] = 0
           v_parts[i-1] += 1
           print('.'.join(map(str, v_parts)))
           except Exception as e:
           print(cur_ver)
\")"""

new_fragment = """           NEW_VER=$(python3 -c "
           import sys
           cur_ver = '$CUR_VER'
           fmt_str = '$FORMAT'
           try:
               v_parts = [int(x) for x in cur_ver.split('.')]
               f_parts = fmt_str.split('.')
               v_parts[-1] += 1
               for i in range(len(v_parts)-1, 0, -1):
                   width = f_parts[i].count('#')
                   limit = 10**width
                   if v_parts[i] >= limit:
                       v_parts[i] = 0
                       v_parts[i-1] += 1
               print('.'.join(map(str, v_parts)))
           except Exception as e:
               print(cur_ver)
           \")"""

if old_fragment in content:
    content = content.replace(old_fragment, new_fragment)
    with open(filepath, 'w') as f:
        f.write(content)
    print("Replacement successful")
else:
    print("Old fragment not found exactly")
