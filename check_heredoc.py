import sys

def check_file(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()

    stack = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Check for start
        if '<<' in line:
            # Very simple parser
            parts = line.split('<<')
            if len(parts) > 1:
                marker = parts[1].strip().strip("'").strip('"')
                if marker and marker[0].isalpha():
                    stack.append((marker, i))
                    # print(f"Start {marker} at line {i}")

        # Check for end
        if stack:
            current_marker, start_line = stack[-1]
            if line.rstrip() == current_marker:
                # print(f"End {current_marker} at line {i}")
                stack.pop()

    for marker, line in stack:
        print(f"Unclosed here-doc {marker} starting at line {line}")

if __name__ == "__main__":
    check_file(sys.argv[1])
