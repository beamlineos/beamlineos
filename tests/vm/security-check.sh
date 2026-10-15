# SPDX-License-Identifier: MIT
#
# Negative security tests (ci/test-security; docs/security.md §15; docs/decisions.md D59), on an
# enforcing production boot. beamline-security-check.service runs this as root in
# platform_service_t, the domain of services without one of their own (D90); every check runs in the context it tests, through a transient unit
# (systemd-run --pipe, with SELinuxContext= and User=). Checks that must be refused run as root,
# so that SELinux, not file permissions, is what refuses them. Each refusal they provoke is listed
# in policy/selinux-expected.toml. Never part of an image.

set -u
P0=user_u:user_r:user_t:s0:c0
ADMIN=admin_u:admin_r:admin_t:s2:c0.c1023
UPDATER=system_u:system_r:sysupdate_t:s3:c0.c1023
failed=0

result() {
    if [ "$2" = ok ]; then echo "SECURITY $1: ok"; else echo "SECURITY $1: FAILED ($3)"; failed=1; fi
}

# run CONTEXT USER COMMAND: the command's output, then its exit status as "status=N".
run() {
    systemd-run --quiet --wait --pipe --collect --property="SELinuxContext=$1" \
        --property="User=$2" /usr/bin/sh -c "$3" 2>&1
    echo "status=$?"
}

read -r enforce < /sys/fs/selinux/enforce
[ "$enforce" = 1 ] && result enforcing ok || result enforcing failed "SELinux is not enforcing"

# The posix extension provides cp, insmod, readlink and setenforce.
beamlinectl --no-ask-password activate posix

# A process's context: attr/current ends in a NUL, not a newline, so read reports end of file even
# when it read the context; an empty result means the process is gone.
context() {
    c=
    { read -r c < "/proc/$1/attr/current"; } 2>/dev/null
    printf %s "$c"
}

# The kernel label of the verified CLI itself, during execution from a P0 session.
# Observe the executable's process, rather than inferring it from its parent or exit status.
systemd-tmpfiles --create --inline 'd /run/beamline-security-ctl 0755 - - -'
observe_cli() {
    while [ ! -e /run/beamline-security-ctl/done ]; do
        for process in /proc/[0-9]*; do
            command=
            { read -r command < "$process/comm"; } 2>/dev/null || :
            [ "$command" = beamlinectl ] || continue
            c=$(context "${process#/proc/}")
            case "$c" in
                "$P0"*) : > /run/beamline-security-ctl/p0 ;;
                '') ;;
                *) echo "unexpected CLI domain: $c"; : > /run/beamline-security-ctl/wrong ;;
            esac
        done
    done
}
observe_cli & cli_observer=$!
for _round in 1 2 3 4 5; do
    if ! systemd-run --quiet --wait --pipe --collect --property=User=alice \
        --property="SELinuxContext=$P0" /usr/bin/beamlinectl --json list; then
        : > /run/beamline-security-ctl/wrong
    fi
done
: > /run/beamline-security-ctl/done
wait "$cli_observer"
if [ -e /run/beamline-security-ctl/p0 ] && [ ! -e /run/beamline-security-ctl/wrong ]; then
    result verified-cli-domain ok
else
    result verified-cli-domain failed 'did not observe the verified CLI remaining in P0'
fi

# PID 1 alone runs in init_t (D90): every init_t process runs systemd's own binaries (PID 1, its
# executor, and the PAM holder forked from it), never a service. Services without a domain of
# their own, this harness among them, run in platform_service_t.
strays=
checked=0
for attr in /proc/[0-9]*/attr/current; do
    pid=${attr#/proc/}; pid=${pid%%/*}
    c=$(context "$pid")
    [ -n "$c" ] || continue
    checked=$((checked + 1))
    case "$c" in *:init_t:*) ;; *) continue ;; esac
    exe=$(readlink "/proc/$pid/exe" 2>/dev/null)
    case "$exe" in /usr/lib/systemd/systemd|/usr/lib/systemd/systemd-executor) ;; *) strays="$strays $pid:$exe" ;; esac
done
if [ "$checked" -lt 10 ]; then result init-alone failed "read only $checked contexts"
elif [ -n "$strays" ]; then result init-alone failed "$strays"
else result init-alone ok; fi
c=$(context $$)
case "$c" in *:platform_service_t:*) result service-default-domain ok ;; *) result service-default-domain failed "$c" ;; esac

# Confined services run in their own domains (D91), judged by each unit's main process.
for pair in systemd-journald:journald_t systemd-udevd:udevd_t dbus-broker:dbusd_t polkit:polkitd_t \
    systemd-logind:logind_t systemd-networkd:networkd_t systemd-resolved:resolved_t \
    avahi-daemon:avahi_t; do
    # polkit is started on demand (D-Bus activation)
    systemctl start "${pair%%:*}.service"
    pid=$(systemctl show -P MainPID "${pair%%:*}.service")
    c=$(context "$pid")
    [ -n "$c" ] || c="no main process ($pid)"
    case "$c" in *":${pair#*:}:"*) result "domain-${pair%%:*}" ok ;; *) result "domain-${pair%%:*}" failed "$c" ;; esac
done

# MLS levels (D99, docs/security-mls.md §3.2, §6): every subject and object carries the level its
# integrity assigns: platform s3 with every category, run0 and /etc s2, sessions s0 with the shared
# category, shared low containers s0. getfilecon comes with the posix extension.
level_of() {  # CONTEXT: its level, everything after the type
    printf %s "$1" | { IFS=: read -r _u _r _t level; printf %s "$level"; }
}
file_level() {  # PATH: its file's level
    getfilecon "$1" 2> /dev/null | { read -r _p c; level_of "$c"; }
}
levels_ok=1
check_level() {  # NAME LEVEL EXPECTED
    [ "$2" = "$3" ] || { echo "level $1: $2, expected $3"; levels_ok=0; }
}
check_level pid1 "$(level_of "$(context 1)")" s3:c0.c1023
check_level harness "$(level_of "$(context $$)")" s3:c0.c1023
check_level journald "$(level_of "$(context "$(systemctl show -P MainPID systemd-journald.service)")")" s3:c0.c1023
for path in /usr/bin/dash /etc/os-release /var/lib /run/systemd; do
    check_level "$path" "$(file_level "$path")" s3:c0.c1023
done
check_level /etc "$(file_level /etc)" s2:c0.c1023
check_level /tmp "$(file_level /tmp)" s0
out=$(run "$P0" alice 'read -r c < /proc/self/attr/current; echo "P0_CONTEXT=$c"')
case "$out" in *"P0_CONTEXT=$P0"*) ;; *) echo "level session: $out"; levels_ok=0 ;; esac
out=$(run "$ADMIN" root 'read -r c < /proc/self/attr/current; echo "ADMIN_CONTEXT=$c"')
case "$out" in *"ADMIN_CONTEXT=$ADMIN"*) ;; *) echo "level admin: $out"; levels_ok=0 ;; esac
[ "$levels_ok" = 1 ] && result mls-levels ok || result mls-levels failed "see above"

# The ring-variant Biba (D100, docs/security-mls.md): cases Type Enforcement allows and the MLS
# constraints refuse. All run as root, so neither DAC nor TE is what refuses them.
# P0 creates a file in /run/systemd: TE lets user_t add entries to run_t directories (for the
# mount points of its own namespaces), but /run/systemd is P3.
out=$(run "$P0" root ': > /run/systemd/beamline-p0 && echo WROTE_RUN')
case "$out" in *WROTE_RUN*) result mls-p0-writes-run failed "$out"; rm -f /run/systemd/beamline-p0 ;; *) result mls-p0-writes-run ok ;; esac
# A run0 session creates a FIFO in a P3 run_t directory: TE lets admin_t write run_t directories
# (for run0's password agent), but only /run/systemd/ask-password-block is P2.
out=$(run "$ADMIN" root 'mkfifo /run/systemd/beamline-admin-fifo && echo MADE_FIFO')
case "$out" in *MADE_FIFO*) result mls-admin-writes-run failed "$out"; rm -f /run/systemd/beamline-admin-fifo ;; *) result mls-admin-writes-run ok ;; esac
# P0 overwrites a file a platform service created in /tmp: TE lets user_t write tmp_t, but the file
# is P3, as its creator.
printf 'platform\n' > /tmp/beamline-p3-file
out=$(run "$P0" root 'printf "p0\n" >> /tmp/beamline-p3-file && echo WROTE_TMP')
case "$out" in *WROTE_TMP*) result mls-p0-writes-p3-tmp failed "$out" ;; *) result mls-p0-writes-p3-tmp ok ;; esac
rm -f /tmp/beamline-p3-file

# SYSTEM's root hash is signed (D101): the kernel checked the signature when the initrd activated
# the root, so the active verity table names the signature's key.
table=$(dmsetup table root 2> /dev/null)
case "$table" in *root_hash_sig_key_desc*) result system-roothash-signed ok ;; *) result system-roothash-signed failed "$table" ;; esac

# IPE (D102): the kernel loads modules only from a verified source. As root in a platform domain,
# which SELinux lets load modules, a file on DATA is refused by IPE (permission denied), while a
# file on SYSTEM passes IPE and fails only the module checks that follow.
cp /usr/bin/dash /var/tmp/beamline-ipe-module
out=$(insmod /var/tmp/beamline-ipe-module 2>&1)
case "$out" in *"ermission denied"*) result ipe-data-module ok ;; *) result ipe-data-module failed "$out" ;; esac
out=$(insmod /usr/bin/dash 2>&1)
case "$out" in *"ermission denied"*|"") result ipe-system-module failed "$out" ;; *) result ipe-system-module ok ;; esac
rm -f /var/tmp/beamline-ipe-module
read -r ipe_policy < /sys/kernel/security/ipe/policies/beamline_boot/name 2> /dev/null
[ "$ipe_policy" = beamline_boot ] && result ipe-boot-policy ok || result ipe-boot-policy failed "${ipe_policy:-none}"

# P0 executes an arbitrary, unsigned ELF it placed in a writable directory: allowed.
out=$(run "$P0" alice 'cp /usr/bin/dash /var/tmp/p0-elf && /var/tmp/p0-elf -c "echo P0_ELF_RAN"')
case "$out" in *P0_ELF_RAN*) result p0-runs-own-elf ok ;; *) result p0-runs-own-elf failed "$out" ;; esac

# P0 modifies verified /usr: refused (read-only, verity-backed SYSTEM).
out=$(run "$P0" root ': > /usr/lib/beamline-p0 && echo WROTE_USR')
case "$out" in *WROTE_USR*) result p0-writes-usr failed "$out" ;; *) result p0-writes-usr ok ;; esac

# P0 and admin write a file outside /etc's allowlist: refused by SELinux, even as root.
for who in p0:"$P0" admin:"$ADMIN"; do
    out=$(run "${who#*:}" root 'printf "# beamline\n" >> /etc/pam.d/login && echo WROTE_ETC')
    case "$out" in *WROTE_ETC*) result "${who%%:*}-writes-etc" failed "$out" ;; *) result "${who%%:*}-writes-etc" ok ;; esac
done

# admin changes an allowlisted setting in place: allowed.
out=$(run "$ADMIN" root 'printf "beamline-security\n" > /etc/hostname && echo WROTE_HOSTNAME')
case "$out" in *WROTE_HOSTNAME*) result admin-writes-setting ok ;; *) result admin-writes-setting failed "$out" ;; esac

# P0 enters the updater's or the admin domain through /proc/self/attr/exec: refused.
for target in sysupdate:"$UPDATER" admin:"$ADMIN"; do
    out=$(run "$P0" root "printf %s '${target#*:}' > /proc/self/attr/exec && exec /usr/bin/sh -c 'echo ENTERED'")
    case "$out" in *ENTERED*) result "p0-enters-${target%%:*}" failed "$out" ;; *) result "p0-enters-${target%%:*}" ok ;; esac
done

# The P3 updater executes a helper from /var/tmp: refused.
out=$(run "$UPDATER" root '/var/tmp/p0-elf -c "echo HELPER_RAN"')
case "$out" in *HELPER_RAN*) result updater-runs-tmp-helper failed "$out" ;; *) result updater-runs-tmp-helper ok ;; esac

# admin switches SELinux to permissive: refused, and enforcement stays on.
out=$(run "$ADMIN" root 'setenforce 0 && echo SETENFORCE_DONE')
read -r enforce < /sys/fs/selinux/enforce
case "$out:$enforce" in *SETENFORCE_DONE*|*:0) result admin-setenforce failed "$out" ;; *) result admin-setenforce ok ;; esac

# admin loads a kernel module (any file; it is not signed): refused.
out=$(run "$ADMIN" root 'insmod /var/tmp/p0-elf && echo MODULE_LOADED')
case "$out" in *MODULE_LOADED*) result admin-loads-module failed "$out" ;; *) result admin-loads-module ok ;; esac

# Sessions bind TCP and UDP sockets on unreserved ports (security §4.2, D84): allowed. Port 8080
# lies below the ephemeral range, so SELinux checks name_bind as well as node_bind.
for proto in tcp udp; do
    flag=; [ "$proto" = udp ] && flag=--datagram
    out=$(run "$P0" alice "systemd-socket-activate --now $flag -l 127.0.0.1:8080 /usr/bin/true && echo BOUND")
    case "$out" in *BOUND*status=0*) result "p0-binds-$proto" ok ;; *) result "p0-binds-$proto" failed "$out" ;; esac
done
# Ports below 1024 stay closed, even to a P0 process with UID 0: user_t holds no net_bind_service.
out=$(run "$P0" root 'systemd-socket-activate --now -l 127.0.0.1:80 /usr/bin/true && echo BOUND')
case "$out" in *BOUND*) result p0-binds-reserved failed "$out" ;; *) result p0-binds-reserved ok ;; esac

# admin reads a disk (fdisk, blkid; D84): allowed. Opening it for writing: refused, before any
# byte could be written (count=0).
out=$(run "$ADMIN" root 'dd if=/dev/vda of=/dev/null bs=512 count=1 status=none && echo READ_DISK')
case "$out" in *READ_DISK*) result admin-reads-disk ok ;; *) result admin-reads-disk failed "$out" ;; esac
out=$(run "$ADMIN" root 'dd if=/dev/null of=/dev/vda count=0 conv=notrunc status=none && echo OPENED_DISK')
case "$out" in *OPENED_DISK*) result admin-writes-disk failed "$out" ;; *) result admin-writes-disk ok ;; esac

# systemd's empower group and its polkit rule are absent (D76, step 1).
empower=
while IFS=: read -r name _; do [ "$name" = empower ] && empower=group; done < /etc/group
[ -e /usr/share/polkit-1/rules.d/empower.rules ] && empower="$empower rule"
[ -z "$empower" ] && result empower-absent ok || result empower-absent failed "$empower"

# alice reads dev's home while dev's home is active: refused.
PASSWORD=dev homectl activate dev
out=$(run "$P0" alice 'cd /home/dev && echo READ_DEV_HOME')
homectl deactivate dev
case "$out" in *READ_DEV_HOME*) result p0-reads-other-home failed "$out" ;; *) result p0-reads-other-home ok ;; esac

# A P0 process with UID 0 reaches polkit's root path, so these refusals exercise
# the authenticated creator's SELinux bound rather than lack of authorization.
for context in "$P0" "$ADMIN"; do
    out=$(run "$context" root 'systemd-run --quiet --wait --pipe --collect -p SELinuxContext=system_u:system_r:init_t:s0 /usr/bin/sh -c "echo TRANSIENT_ENTERED_INIT"')
    case "$out" in
        *TRANSIENT_ENTERED_INIT*) result transient-explicit-init failed "$out" ;;
        *"Failed to start transient service unit: Access denied"*status=1*) result transient-explicit-init ok ;;
        *) result transient-explicit-init failed "unexpected refusal (the harness also requires the SELinux transition audit): $out" ;;
    esac
done

# A caller-controlled root may hide procfs with ordinary writable attr files.
# Read actual task context through a separately bound host procfs; never trust the fixture.
fake=/var/tmp/beamline-transient-root
mkdir -p "$fake/proc/thread-self/attr" "$fake/proc/self/attr" "$fake/usr" "$fake/host-proc"
ln -s usr/bin "$fake/bin"
ln -s usr/lib "$fake/lib"
ln -s usr/lib "$fake/lib64"
: > "$fake/proc/thread-self/attr/exec"
: > "$fake/proc/self/attr/exec"
# P3 launches this P0 harness; P0 itself then creates the transient unit under test.
out=$(run "$P0" root "systemd-run --quiet --wait --pipe --collect -p RootDirectory=$fake -p MountAPIVFS=no -p BindReadOnlyPaths=/usr -p BindReadOnlyPaths=/proc:/host-proc /usr/bin/sh -c 'read -r c < /host-proc/self/attr/current; echo ACTUAL_ROOT_CONTEXT=\"\$c\"'")
case "$out" in
    *ACTUAL_ROOT_CONTEXT=user_u:user_r:user_t:s0:c0*) result transient-fake-proc ok ;;
    *) result transient-fake-proc failed "$out" ;;
esac
rm -rf "$fake"

# A namespace fork must set the child task's exec context.
out=$(run "$P0" root "systemd-run --quiet --wait --pipe --collect -p PrivatePIDs=yes /usr/bin/sh -c 'read -r c < /proc/self/attr/current; echo PRIVATE_CONTEXT=\"\$c\"'")
case "$out" in
    *PRIVATE_CONTEXT=user_u:user_r:user_t:s0:c0*) result transient-private-pids ok ;;
    *) result transient-private-pids failed "$out" ;;
esac

# PID 1's other transient-unit interface, varlink io.systemd.Unit.StartTransient, must bind the
# creator too (D72). The varlink schema exposes no SELinuxContext, so the unit takes the default
# context; without the bound it would inherit PID 1's init_t. The marker file is written by the
# transient unit itself, so its content is the unit's own execution context, not the caller's.
vljson='{"context":{"ID":"beamline-vltransient.service","Service":{"Type":"oneshot","RemainAfterExit":true,"ExecStart":[{"path":"/usr/bin/sh","arguments":["sh","-c","read -r c < /proc/self/attr/current; printf %s \"$c\" > /var/tmp/beamline-vltransient"]}]}},"mode":"replace"}'
out=$(run "$P0" root "rm -f /var/tmp/beamline-vltransient; varlinkctl call /run/systemd/io.systemd.Manager io.systemd.Unit.StartTransient '$vljson' >/dev/null 2>&1; for _ in 1 2 3 4 5; do [ -s /var/tmp/beamline-vltransient ] && break; sleep 1; done; read -r c < /var/tmp/beamline-vltransient; echo VARLINK_CONTEXT=\"\$c\"; rm -f /var/tmp/beamline-vltransient")
case "$out" in
    *VARLINK_CONTEXT=user_u:user_r:user_t:s0:c0*) result transient-varlink-default ok ;;
    *) result transient-varlink-default failed "$out" ;;
esac

# Fully privileged command flags must preserve the creator's bound. Keep the unit
# around to prove that manager reload/reexec does not discard that private state.
cp "$CREDENTIALS_DIRECTORY/beamline.test.transient-edges" /var/tmp/beamline-transient-edges.sh
chmod 644 /var/tmp/beamline-transient-edges.sh
out=$(run "$P0" root '/usr/bin/sh /var/tmp/beamline-transient-edges.sh')
case "$out" in
    *TRANSIENT_PRIVILEGED_P0*) result transient-privileged ok ;;
    *) result transient-privileged failed "$out" ;;
esac
for operation in daemon-reload daemon-reexec; do
    systemctl "$operation"
    rm -f /var/tmp/beamline-transient-context
    if systemctl restart beamline-transient-privileged.service; then
        read -r context < /var/tmp/beamline-transient-context
        [ "$context" = "$P0" ] && result "transient-$operation" ok || result "transient-$operation" failed "$context"
    else
        result "transient-$operation" failed 'restart failed'
    fi
done
systemctl stop beamline-transient-privileged.service
rm -f /var/tmp/beamline-transient-edges.sh /var/tmp/beamline-transient-context

# Unit definitions load only from labels PID 1 trusts (D97). A unit linked from /var/tmp, which a
# lower level can write, is refused when PID 1 loads it, although the link itself is PID 1's.
printf '[Service]\nType=oneshot\nExecStart=/usr/bin/systemd-escape BEAMLINE_LINKED_UNIT_RAN\n' > /var/tmp/beamline-linked.service
systemctl link --runtime /var/tmp/beamline-linked.service
systemctl daemon-reload
systemctl start beamline-linked.service 2> /dev/null
state=$(systemctl show -P LoadState beamline-linked.service)
[ "$state" = error ] && result unit-linked-refused ok || result unit-linked-refused failed "$state"
systemctl disable --runtime beamline-linked.service 2> /dev/null
rm -f /var/tmp/beamline-linked.service
# Only PID 1 writes its runtime unit directory: a platform service (this harness) and a run0 session
# are refused, even as root.
out=$( { printf '[Service]\n' > /run/systemd/system/beamline-written.service && echo WROTE_UNIT; } 2>&1)
case "$out" in *WROTE_UNIT*) result platform-writes-unit failed "$out" ;; *) result platform-writes-unit ok ;; esac
out=$(run "$ADMIN" root 'printf "[Service]\n" > /run/systemd/system/beamline-written.service && echo WROTE_UNIT')
case "$out" in *WROTE_UNIT*) result admin-writes-unit failed "$out" ;; *) result admin-writes-unit ok ;; esac
# Generators still define units: the fstab generator's DATA mount is loaded from its output
fragment=$(systemctl show -P FragmentPath data.mount)
state=$(systemctl show -P LoadState data.mount)
case "$state:$fragment" in loaded:/run/systemd/generator/*) result generator-units-load ok ;; *) result generator-units-load failed "$state:$fragment" ;; esac

rm -f /var/tmp/p0-elf
[ "$failed" = 0 ] && echo BEAMLINE_SECURITY_OK || echo BEAMLINE_SECURITY_FAILED
