"""Host-independent QEMU guest policy shared by CLI and desktop frontend."""
CPU_COUNTS = (1, 2, 4)
LOCK_TIMEOUT_SECONDS = 5


def multicore_boot_args(cpu_count):
    if cpu_count not in CPU_COUNTS:
        raise ValueError('CPU count must be 1, 2, or 4')
    if cpu_count == 1:
        return ''
    # XNU arm64 machine_routines.c legacy slto_us/tlto_us use microseconds.
    # locks_arm.c "lock-panic" uses machine.c's external TIMEBASE input:
    # picoseconds / 1000 -> nanoseconds -> architectural timer ticks.
    # Both forms below specify FIVE SECONDS. Deadlock detection stays finite.
    microseconds = LOCK_TIMEOUT_SECONDS * 1_000_000
    picoseconds = LOCK_TIMEOUT_SECONDS * 1_000_000_000_000
    return (f'slto_us={microseconds} tlto_us={microseconds} '
            f'ml-timeout-lock-panic={picoseconds}')
