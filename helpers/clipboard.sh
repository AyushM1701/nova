#!/bin/sh
# Copy files to the clipboard (paste them in Finder, Mail or chat), or with -Image copy a picture's pixels.
# Usage: clipboard.sh "<file>" ["<file>" ...] [-Image]
exec osascript -l JavaScript - "$@" <<'EOF'
ObjC.import('AppKit');
function run(argv) {
  const image = argv.includes('-Image');
  const cwd = $.NSFileManager.defaultManager.currentDirectoryPath.js;
  const paths = argv.filter(a => a !== '-Image').map(p => (p.startsWith('/') ? p : cwd + '/' + p));
  const fm = $.NSFileManager.defaultManager;
  paths.forEach(p => { if (!fm.fileExistsAtPath(p)) throw new Error('No such file: ' + p); });
  const pb = $.NSPasteboard.generalPasteboard;
  pb.clearContents;
  if (image) {
    const img = $.NSImage.alloc.initWithContentsOfFile(paths[0]);
    if (img.isNil()) throw new Error('Not an image: ' + paths[0]);
    pb.writeObjects($([img]));
    return 'Copied the image ' + paths[0] + ' to the clipboard.';
  }
  pb.writeObjects($(paths.map(p => $.NSURL.fileURLWithPath(p))));
  return 'Copied ' + paths.length + ' file(s) to the clipboard.';
}
EOF
