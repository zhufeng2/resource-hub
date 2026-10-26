#!/usr/bin/env python3
"""Install the two skill definitions; account authorization stays on each device."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import tempfile

NAMES = ('resource-hub', 'quarkclouddrive')


def main():
    default = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-dir', type=Path, default=default,
                        help='Skill directory (default: $CODEX_HOME/skills or ~/.codex/skills)')
    parser.add_argument('--update', action='store_true', help='Back up existing skills before updating')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / 'skills'
    destination = args.skills_dir.expanduser().resolve()
    for name in NAMES:
        if not (source / name / 'SKILL.md').is_file():
            parser.error(f'Missing source skill: {name}')
        target = destination / name
        if target.is_symlink():
            parser.error(f'Refusing to replace symlink: {target}')
        if target.exists() and not args.update:
            parser.error(f'{target} exists. Use --update to back it up and update.')
        if target.exists() and not target.is_dir():
            parser.error(f'Target is not a directory: {target}')
    destination.mkdir(parents=True, exist_ok=True)
    backup = None
    existing = [name for name in NAMES if (destination / name).exists()]
    if existing:
        parent = destination.parent / 'skill-backups'
        parent.mkdir(parents=True, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=parent))
        for name in existing:
            shutil.copytree(destination / name, backup / name)
        print(f'Backup: {backup}')
    for name in NAMES:
        # Merge preserves the official CLI and device-local account state during sync.
        shutil.copytree(source / name, destination / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', '.cache',
                            'node_modules', '.env*', 'credentials.json', 'config.json', '*.sqlite*', '*.db', '*.mcp.key'))
        print(f'Installed: {destination / name}')
    print('Open a new chat to load the skills. Connect Resource Hub MCP in your assistant and authorize Quark on this device.')


if __name__ == '__main__':
    main()
