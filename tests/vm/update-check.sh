# SPDX-License-Identifier: MIT
# Candidate/previous-version update and rollback probe, injected as a credential.
set -eu
. /usr/lib/os-release
read -r enforcing < /sys/fs/selinux/enforce || [ -n "$enforcing" ]
[ "$enforcing" = 1 ]
echo "BEAMLINE_UPDATE_ENFORCING $IMAGE_VERSION"
read -r old < "$CREDENTIALS_DIRECTORY/beamline.test.old" || [ -n "$old" ]
read -r new < "$CREDENTIALS_DIRECTORY/beamline.test.new" || [ -n "$new" ]
state=/var/lib/beamline-test
echo "booted $IMAGE_VERSION (old $old, new $new)"
choice_kept() {
    beamlinectl list > /run/beamline-update-choices
    while read -r name enabled active available live; do
        [ "$name" = posix ] || continue
        [ "$enabled" = yes ]
        return $?
    done < /run/beamline-update-choices
    return 1
}
if [ "$IMAGE_VERSION" = "$old" ] && [ -e "$state/updated" ]; then
    [ -e "$state/marker" ]
    if [ -e "$state/ctl-choice" ]; then choice_kept; echo BEAMLINE_CTL_ROLLBACK_CHOICE_OK; fi
    echo BEAMLINE_ROLLED_BACK
elif [ "$IMAGE_VERSION" = "$old" ]; then
    systemd-tmpfiles --create --inline "d $state 0755 - - -" "f $state/marker 0644 - - - kept"
    /usr/lib/systemd/systemd-sysupdate update
    : > "$state/updated"
    systemctl --no-block reboot
elif [ "$IMAGE_VERSION" = "$new" ]; then
    bootctl list --no-pager || true
    [ -e "$state/marker" ]
    /usr/lib/systemd/systemd-sysupdate update "$new"
    for version in "$old" "$new"; do [ -e "/var/lib/beamline/extensions/desktop-gnome_$version.raw" ]; done
    for extension in printing-scanning posix-devel; do
        [ -e "/var/lib/beamline/extensions/${extension}_$new.raw" ]
        [ -e "/var/lib/beamline/confexts/${extension}_$new.raw" ]
    done
    beamlinectl enable posix
    choice_kept
    : > "$state/ctl-choice"
    beamlinectl --no-ask-password activate posix
    bash --version >/dev/null
    echo BEAMLINE_CTL_UPDATE_CHOICE_OK
    echo BEAMLINE_UPDATED_OK
else
    echo "unexpected version $IMAGE_VERSION"; exit 1
fi
