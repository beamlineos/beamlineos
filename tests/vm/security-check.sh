# SPDX-License-Identifier: MIT








set -u
P0=user_u:user_r:user_t:s0:c0
ADMIN=admin_u:admin_r:admin_t:s2:c0.c1023
UPDATER=system_u:system_r:sysupdate_t:s3:c0.c1023
failed=0

result() {
    if [ "$2" = ok ]; then echo "SECURITY $1: ok"; else echo "SECURITY $1: FAILED ($3)"; failed=1; fi
}


run() {
    systemd-run --quiet --wait --pipe --collect --property="SELinuxContext=$1" \
        --property="User=$2" /usr/bin/sh -c "$3" 2>&1
    echo "status=$?"
}

read -r enforce < /sys/fs/selinux/enforce
[ "$enforce" = 1 ] && result enforcing ok || result enforcing failed "SELinux is not enforcing"


beamlinectl --no-ask-password activate posix



context() {
    c=
    { read -r c < "/proc/$1/attr/current"; } 2>/dev/null
    printf %s "$c"
}



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


for pair in systemd-journald:journald_t systemd-udevd:udevd_t dbus-broker:dbusd_t polkit:polkitd_t \
    systemd-logind:logind_t systemd-networkd:networkd_t systemd-resolved:resolved_t \
    avahi-daemon:avahi_t; do
    
    systemctl start "${pair%%:*}.service"
    pid=$(systemctl show -P MainPID "${pair%%:*}.service")
    c=$(context "$pid")
    [ -n "$c" ] || c="no main process ($pid)"
    case "$c" in *":${pair#*:}:"*) result "domain-${pair%%:*}" ok ;; *) result "domain-${pair%%:*}" failed "$c" ;; esac
done




level_of() {                                                 
    printf %s "$1" | { IFS=: read -r _u _r _t level; printf %s "$level"; }
}
file_level() {                          
    getfilecon "$1" 2> /dev/null | { read -r _p c; level_of "$c"; }
}
levels_ok=1
check_level() {                       
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





out=$(run "$P0" root ': > /run/systemd/beamline-p0 && echo WROTE_RUN')
case "$out" in *WROTE_RUN*) result mls-p0-writes-run failed "$out"; rm -f /run/systemd/beamline-p0 ;; *) result mls-p0-writes-run ok ;; esac


out=$(run "$ADMIN" root 'mkfifo /run/systemd/beamline-admin-fifo && echo MADE_FIFO')
case "$out" in *MADE_FIFO*) result mls-admin-writes-run failed "$out"; rm -f /run/systemd/beamline-admin-fifo ;; *) result mls-admin-writes-run ok ;; esac


printf 'platform\n' > /tmp/beamline-p3-file
out=$(run "$P0" root 'printf "p0\n" >> /tmp/beamline-p3-file && echo WROTE_TMP')
case "$out" in *WROTE_TMP*) result mls-p0-writes-p3-tmp failed "$out" ;; *) result mls-p0-writes-p3-tmp ok ;; esac
rm -f /tmp/beamline-p3-file



table=$(dmsetup table root 2> /dev/null)
case "$table" in *root_hash_sig_key_desc*) result system-roothash-signed ok ;; *) result system-roothash-signed failed "$table" ;; esac




cp /usr/bin/dash /var/tmp/beamline-ipe-module
out=$(insmod /var/tmp/beamline-ipe-module 2>&1)
case "$out" in *"ermission denied"*) result ipe-data-module ok ;; *) result ipe-data-module failed "$out" ;; esac
out=$(insmod /usr/bin/dash 2>&1)
case "$out" in *"ermission denied"*|"") result ipe-system-module failed "$out" ;; *) result ipe-system-module ok ;; esac
rm -f /var/tmp/beamline-ipe-module
read -r ipe_policy < /sys/kernel/security/ipe/policies/beamline_boot/name 2> /dev/null
[ "$ipe_policy" = beamline_boot ] && result ipe-boot-policy ok || result ipe-boot-policy failed "${ipe_policy:-none}"


out=$(run "$P0" alice 'cp /usr/bin/dash /var/tmp/p0-elf && /var/tmp/p0-elf -c "echo P0_ELF_RAN"')
case "$out" in *P0_ELF_RAN*) result p0-runs-own-elf ok ;; *) result p0-runs-own-elf failed "$out" ;; esac


out=$(run "$P0" root ': > /usr/lib/beamline-p0 && echo WROTE_USR')
case "$out" in *WROTE_USR*) result p0-writes-usr failed "$out" ;; *) result p0-writes-usr ok ;; esac


for who in p0:"$P0" admin:"$ADMIN"; do
    out=$(run "${who#*:}" root 'printf "# beamline\n" >> /etc/pam.d/login && echo WROTE_ETC')
    case "$out" in *WROTE_ETC*) result "${who%%:*}-writes-etc" failed "$out" ;; *) result "${who%%:*}-writes-etc" ok ;; esac
done


out=$(run "$ADMIN" root 'printf "beamline-security\n" > /etc/hostname && echo WROTE_HOSTNAME')
case "$out" in *WROTE_HOSTNAME*) result admin-writes-setting ok ;; *) result admin-writes-setting failed "$out" ;; esac


for target in sysupdate:"$UPDATER" admin:"$ADMIN"; do
    out=$(run "$P0" root "printf %s '${target#*:}' > /proc/self/attr/exec && exec /usr/bin/sh -c 'echo ENTERED'")
    case "$out" in *ENTERED*) result "p0-enters-${target%%:*}" failed "$out" ;; *) result "p0-enters-${target%%:*}" ok ;; esac
done


out=$(run "$UPDATER" root '/var/tmp/p0-elf -c "echo HELPER_RAN"')
case "$out" in *HELPER_RAN*) result updater-runs-tmp-helper failed "$out" ;; *) result updater-runs-tmp-helper ok ;; esac


out=$(run "$ADMIN" root 'setenforce 0 && echo SETENFORCE_DONE')
read -r enforce < /sys/fs/selinux/enforce
case "$out:$enforce" in *SETENFORCE_DONE*|*:0) result admin-setenforce failed "$out" ;; *) result admin-setenforce ok ;; esac


out=$(run "$ADMIN" root 'insmod /var/tmp/p0-elf && echo MODULE_LOADED')
case "$out" in *MODULE_LOADED*) result admin-loads-module failed "$out" ;; *) result admin-loads-module ok ;; esac



for proto in tcp udp; do
    flag=; [ "$proto" = udp ] && flag=--datagram
    out=$(run "$P0" alice "systemd-socket-activate --now $flag -l 127.0.0.1:8080 /usr/bin/true && echo BOUND")
    case "$out" in *BOUND*status=0*) result "p0-binds-$proto" ok ;; *) result "p0-binds-$proto" failed "$out" ;; esac
done

out=$(run "$P0" root 'systemd-socket-activate --now -l 127.0.0.1:80 /usr/bin/true && echo BOUND')
case "$out" in *BOUND*) result p0-binds-reserved failed "$out" ;; *) result p0-binds-reserved ok ;; esac



out=$(run "$ADMIN" root 'dd if=/dev/vda of=/dev/null bs=512 count=1 status=none && echo READ_DISK')
case "$out" in *READ_DISK*) result admin-reads-disk ok ;; *) result admin-reads-disk failed "$out" ;; esac
out=$(run "$ADMIN" root 'dd if=/dev/null of=/dev/vda count=0 conv=notrunc status=none && echo OPENED_DISK')
case "$out" in *OPENED_DISK*) result admin-writes-disk failed "$out" ;; *) result admin-writes-disk ok ;; esac


empower=
while IFS=: read -r name _; do [ "$name" = empower ] && empower=group; done < /etc/group
[ -e /usr/share/polkit-1/rules.d/empower.rules ] && empower="$empower rule"
[ -z "$empower" ] && result empower-absent ok || result empower-absent failed "$empower"


PASSWORD=dev homectl activate dev
out=$(run "$P0" alice 'cd /home/dev && echo READ_DEV_HOME')
homectl deactivate dev
case "$out" in *READ_DEV_HOME*) result p0-reads-other-home failed "$out" ;; *) result p0-reads-other-home ok ;; esac



for context in "$P0" "$ADMIN"; do
    out=$(run "$context" root 'systemd-run --quiet --wait --pipe --collect -p SELinuxContext=system_u:system_r:init_t:s0 /usr/bin/sh -c "echo TRANSIENT_ENTERED_INIT"')
    case "$out" in
        *TRANSIENT_ENTERED_INIT*) result transient-explicit-init failed "$out" ;;
        *"Failed to start transient service unit: Access denied"*status=1*) result transient-explicit-init ok ;;
        *) result transient-explicit-init failed "unexpected refusal (the harness also requires the SELinux transition audit): $out" ;;
    esac
done



fake=/var/tmp/beamline-transient-root
mkdir -p "$fake/proc/thread-self/attr" "$fake/proc/self/attr" "$fake/usr" "$fake/host-proc"
ln -s usr/bin "$fake/bin"
ln -s usr/lib "$fake/lib"
ln -s usr/lib "$fake/lib64"
: > "$fake/proc/thread-self/attr/exec"
: > "$fake/proc/self/attr/exec"

out=$(run "$P0" root "systemd-run --quiet --wait --pipe --collect -p RootDirectory=$fake -p MountAPIVFS=no -p BindReadOnlyPaths=/usr -p BindReadOnlyPaths=/proc:/host-proc /usr/bin/sh -c 'read -r c < /host-proc/self/attr/current; echo ACTUAL_ROOT_CONTEXT=\"\$c\"'")
case "$out" in
    *ACTUAL_ROOT_CONTEXT=user_u:user_r:user_t:s0:c0*) result transient-fake-proc ok ;;
    *) result transient-fake-proc failed "$out" ;;
esac
rm -rf "$fake"


out=$(run "$P0" root "systemd-run --quiet --wait --pipe --collect -p PrivatePIDs=yes /usr/bin/sh -c 'read -r c < /proc/self/attr/current; echo PRIVATE_CONTEXT=\"\$c\"'")
case "$out" in
    *PRIVATE_CONTEXT=user_u:user_r:user_t:s0:c0*) result transient-private-pids ok ;;
    *) result transient-private-pids failed "$out" ;;
esac





vljson='{"context":{"ID":"beamline-vltransient.service","Service":{"Type":"oneshot","RemainAfterExit":true,"ExecStart":[{"path":"/usr/bin/sh","arguments":["sh","-c","read -r c < /proc/self/attr/current; printf %s \"$c\" > /var/tmp/beamline-vltransient"]}]}},"mode":"replace"}'
out=$(run "$P0" root "rm -f /var/tmp/beamline-vltransient; varlinkctl call /run/systemd/io.systemd.Manager io.systemd.Unit.StartTransient '$vljson' >/dev/null 2>&1; for _ in 1 2 3 4 5; do [ -s /var/tmp/beamline-vltransient ] && break; sleep 1; done; read -r c < /var/tmp/beamline-vltransient; echo VARLINK_CONTEXT=\"\$c\"; rm -f /var/tmp/beamline-vltransient")
case "$out" in
    *VARLINK_CONTEXT=user_u:user_r:user_t:s0:c0*) result transient-varlink-default ok ;;
    *) result transient-varlink-default failed "$out" ;;
esac



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



printf '[Service]\nType=oneshot\nExecStart=/usr/bin/systemd-escape BEAMLINE_LINKED_UNIT_RAN\n' > /var/tmp/beamline-linked.service
systemctl link --runtime /var/tmp/beamline-linked.service
systemctl daemon-reload
systemctl start beamline-linked.service 2> /dev/null
state=$(systemctl show -P LoadState beamline-linked.service)
[ "$state" = error ] && result unit-linked-refused ok || result unit-linked-refused failed "$state"
systemctl disable --runtime beamline-linked.service 2> /dev/null
rm -f /var/tmp/beamline-linked.service


out=$( { printf '[Service]\n' > /run/systemd/system/beamline-written.service && echo WROTE_UNIT; } 2>&1)
case "$out" in *WROTE_UNIT*) result platform-writes-unit failed "$out" ;; *) result platform-writes-unit ok ;; esac
out=$(run "$ADMIN" root 'printf "[Service]\n" > /run/systemd/system/beamline-written.service && echo WROTE_UNIT')
case "$out" in *WROTE_UNIT*) result admin-writes-unit failed "$out" ;; *) result admin-writes-unit ok ;; esac

fragment=$(systemctl show -P FragmentPath data.mount)
state=$(systemctl show -P LoadState data.mount)
case "$state:$fragment" in loaded:/run/systemd/generator/*) result generator-units-load ok ;; *) result generator-units-load failed "$state:$fragment" ;; esac

rm -f /var/tmp/p0-elf
[ "$failed" = 0 ] && echo BEAMLINE_SECURITY_OK || echo BEAMLINE_SECURITY_FAILED
