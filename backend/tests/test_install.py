"""The optional workflow installer must not retain obsolete executable skills."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install


class InstallerTests(unittest.TestCase):
    def test_upgrade_backs_up_and_removes_old_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'skills'
            old = root / 'resource-hub' / 'scripts'
            old.mkdir(parents=True)
            (old / 'resource.py').write_text('obsolete', encoding='utf-8')
            with patch('sys.argv', ['install.py', '--skills-dir', str(root), '--update']), contextlib.redirect_stdout(io.StringIO()):
                install.main()
            self.assertEqual([p.name for p in (root / 'resource-hub').iterdir()], ['SKILL.md'])
            self.assertFalse((root / 'quarkclouddrive').exists())
            backups = list((Path(tmp) / 'skill-backups').glob('*/resource-hub/scripts/resource.py'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding='utf-8'), 'obsolete')
