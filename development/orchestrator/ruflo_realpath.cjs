// Process-local Windows MXC compatibility. Node's JS realpath implementation
// lstat()s every ancestor, including denied drive/home directories. The native
// implementation resolves an already permitted leaf using Windows handles.
// Filesystem/network enforcement stays in MXC; no access rules are broadened.
const fs = require('node:fs');
if (process.platform === 'win32') {
  const native = fs.realpathSync.native;
  function realpathSync(path, options) { return native(path, options); }
  realpathSync.native = native;
  fs.realpathSync = realpathSync;
}
