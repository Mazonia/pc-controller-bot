import os
import glob
import re

def check_batch_parentheses(filepath):
    errors = []
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    depth = 0
    in_block = False
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('::') or stripped.startswith('rem '):
            continue

        # Check if line has echo with parenthesis while depth > 0
        if depth > 0 and stripped.startswith('echo'):
            echo_content = stripped[4:].strip()
            # If echo contains unescaped ')'
            # Count unescaped closing parens
            unescaped_close = re.findall(r'(?<!\^)\)', echo_content)
            if unescaped_close:
                errors.append((line_num, line.rstrip(), f"Unescaped ')' inside block of depth {depth}"))

        # Track block depth (approximate)
        # Note: ( at end of line opens block
        if re.search(r'(?<!\^)\(\s*$', stripped):
            depth += 1
        # Line consisting of just ) or ) followed by else (
        if re.search(r'^\s*(?<!\^)\)', stripped):
            depth = max(0, depth - 1)
            if re.search(r'else\s+(?<!\^)\(\s*$', stripped):
                depth += 1

    return errors

def main():
    paths = glob.glob(r'c:\Users\Mazonia\Desktop\My Bots\PC-Remote-Sentinel\*.bat') + glob.glob(r'C:\Users\Mazonia\Desktop\PC-Sentinel-SSD-Installer\*.bat')
    found_any = False
    for p in sorted(set(paths)):
        errs = check_batch_parentheses(p)
        if errs:
            found_any = True
            print(f"File: {p}")
            for ln, line, msg in errs:
                print(f"  Line {ln}: {msg}\n    {line}")
    if not found_any:
        print("[OK] No unescaped parentheses found in echo statements within blocks!")

if __name__ == '__main__':
    main()

