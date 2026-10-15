#!/usr/bin/sh
# SPDX-License-Identifier: MIT
# A valid, installed user extension must never be discovered, enabled or downloaded.
set -eu
report_failure() {
    status=$?
    if [ "$status" -ne 0 ]; then
        journalctl --user --no-pager -n 100 || :
        echo BEAMLINE_DESKTOP_FAILED
    fi
}
trap report_failure EXIT
api=org.gnome.Shell.Extensions
fixture=beamline-test@example.test
test -f "/home/dev/.local/share/gnome-shell/extensions/$fixture/extension.js"
test -r "/home/dev/.local/share/gnome-shell/extensions/$fixture/metadata.json"
test -r "/home/dev/.local/share/gnome-shell/extensions/$fixture/extension.js"
# These native Shell services require the retained gjs command.
busctl --user call org.gnome.Shell.Notifications /org/freedesktop/Notifications org.freedesktop.DBus.Peer Ping
busctl --user call org.gnome.ScreenSaver /org/gnome/ScreenSaver org.freedesktop.DBus.Peer Ping
# The previous green desktop lacks vp8enc/webmmux, so upstream's Screencast helper
# exits without owning its bus name. Keep that limitation explicit; any other missing
# requirement or interpreter failure is a test failure (D66).
gst_status=0
gjs -c '
const Gst = imports.gi.Gst;
Gst.init(null);
for (const name of ["pipewiresrc", "filesink", "capsfilter", "videoconvert", "queue"])
    if (!Gst.ElementFactory.find(name))
        throw new Error(`Missing Screencast prerequisite: ${name}`);
const missing = ["vp8enc", "webmmux"].filter(name => !Gst.ElementFactory.find(name));
if (missing.length) {
    print(`Existing Screencast limitation: ${missing.join(", ")}`);
    imports.system.exit(78);
}' || gst_status=$?
case "$gst_status" in
    0) busctl --user --timeout=10s call org.gnome.Shell.Screencast /org/gnome/Shell/Screencast org.freedesktop.DBus.Peer Ping ;;
    78) ;;
    *) exit "$gst_status" ;;
esac
test "$(busctl --user call org.gnome.Shell /org/gnome/Shell "$api" ListExtensions)" = 'a{sa{sv}} 0'
test "$(busctl --user get-property org.gnome.Shell /org/gnome/Shell "$api" UserExtensionsEnabled)" = 'b false'
busctl --user set-property org.gnome.Shell /org/gnome/Shell "$api" UserExtensionsEnabled b true
test "$(busctl --user get-property org.gnome.Shell /org/gnome/Shell "$api" UserExtensionsEnabled)" = 'b false'
test "$(busctl --user call org.gnome.Shell /org/gnome/Shell "$api" EnableExtension s "$fixture")" = 'b false'
if result=$(busctl --user call org.gnome.Shell /org/gnome/Shell "$api" InstallRemoteExtension s "$fixture" 2>&1); then
    echo "UNEXPECTED: downloaded an extension"
    exit 1
fi
case "$result" in
    *'Shell extension support is disabled in this build'*) ;;
    *) echo "UNEXPECTED: $result"; exit 1 ;;
esac
test ! -e /home/dev/beamline-extension-ran
test ! -e /usr/bin/gnome-extensions
test ! -e /usr/bin/lua
test ! -e /usr/bin/wpexec
test ! -e /usr/bin/gjs-console
# The unprivileged document portal must mount its actual FUSE filesystem (D68).
test -u /usr/bin/fusermount3
busctl --user call org.freedesktop.portal.Documents /org/freedesktop/portal/documents org.freedesktop.portal.Documents GetMountPoint
mounted=false
while IFS= read -r entry; do
    case "$entry" in
        *' /run/user/60001/doc '*' - fuse.portal '*) mounted=true ;;
    esac
done < /proc/self/mountinfo
test "$mounted" = true
echo BEAMLINE_DOCUMENT_PORTAL_MOUNTED
echo BEAMLINE_SHELL_EXTENSIONS_DISABLED
