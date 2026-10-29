'use strict';
const fs = require('node:fs');
const path = require('node:path');

// Flush intent before a mutation. A damaged record fails closed on the next read.
// The runner owns the exclusive operation lock for the complete workflow.
function writeJournal(file, record, create = false) {
  const fd = fs.openSync(file, create ? 'wx' : 'w', 0o600);
  try {
    fs.writeFileSync(fd, JSON.stringify(record, null, 2));
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  if (create && process.platform !== 'win32') {
    const directory = fs.openSync(path.dirname(file), 'r');
    try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
  }
}
module.exports = {writeJournal};
