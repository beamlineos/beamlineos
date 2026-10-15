# SPDX-License-Identifier: MIT
#
# One telemetry sample (0.0.4.1, docs/decisions.md D75): pressure stall information, load, memory
# and the two top-level slices' memory, as journal lines with stable keys. dash builtins only: the
# base has no coreutils. tools/daily-telemetry.py collects these lines after a session.

set -u

for resource in cpu memory io; do
    [ -r "/proc/pressure/$resource" ] || continue
    while read -r kind rest; do
        echo "psi $resource $kind $rest"
    done < "/proc/pressure/$resource"
done

read -r l1 l5 l15 tasks _ < /proc/loadavg
echo "load $l1 $l5 $l15 tasks=$tasks"

mem=""
while read -r key value _; do
    case "$key" in
        MemTotal: | MemAvailable: | SwapTotal: | SwapFree: | Shmem:) mem="$mem ${key%:}=$value" ;;
    esac
done < /proc/meminfo
echo "mem$mem"

for slice in system user; do
    f="/sys/fs/cgroup/$slice.slice/memory.current"
    if [ -r "$f" ]; then
        read -r value < "$f"
        echo "cgroup $slice.slice memory.current=$value"
    fi
done
