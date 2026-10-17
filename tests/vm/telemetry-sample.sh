# SPDX-License-Identifier: MIT





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
