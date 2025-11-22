#!/usr/bin/env python3
import sys
import os
from pathlib import Path
import subprocess


def get_tree_structure(folder):
    """Get tree structure, falling back to find if tree not available."""
    try:
        result = subprocess.run(
            ["tree", folder],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to find
        result = subprocess.run(
            ["find", folder, "-print"],
            capture_output=True,
            text=True
        )
        lines = result.stdout.strip().split('\n')
        tree_lines = []
        for line in lines:
            rel = line.replace(folder, '.', 1)
            depth = rel.count('/')
            name = os.path.basename(rel) or '.'
            prefix = '|__' * (depth - 1) if depth > 0 else ''
            tree_lines.append(f"{prefix}{name}")
        return '\n'.join(tree_lines)


def main():
    if len(sys.argv) != 3:
        print("Usage: tree-content <folder_path> <output_file>")
        sys.exit(1)
    
    folder = Path(sys.argv[1])
    output = Path(sys.argv[2])
    
    if not folder.is_dir():
        print(f"Error: {folder} is not a directory")
        sys.exit(1)
    
    with output.open('w') as f:
        f.write("=== Directory Structure ===\n\n")
        f.write(get_tree_structure(str(folder)))
        f.write("\n\n=== File Contents ===\n\n")
        
        for file_path in sorted(folder.rglob('*')):
            if file_path.is_file():
                rel_path = file_path.relative_to(folder)
                f.write("━" * 40 + "\n")
                f.write(f"File: {rel_path}\n")
                f.write("━" * 40 + "\n")
                try:
                    f.write(file_path.read_text())
                except Exception as e:
                    f.write(f"[Error reading file: {e}]")
                f.write("\n\n")
    
    print(f"Output written to {output}")


if __name__ == "__main__":
    main()

