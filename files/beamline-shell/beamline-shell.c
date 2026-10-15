/* SPDX-License-Identifier: MIT */

#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv) {
        (void) argv;

        if (argc != 1 || !isatty(STDIN_FILENO) || !isatty(STDOUT_FILENO)) {
                fputs("beamline-shell cannot interpret commands or scripts.\n", stderr);
                return 1;
        }

        return puts(
                "Beamline does not enable an interactive login shell by default.\n"
                "Ask an administrator to run: beamlinectl enable posix --now\n"
                "A Flatpak terminal can run that command before a shell is available.\n"
                "Then select bash with: homectl update USER --shell=/usr/bin/bash\n"
                "Replace USER with your account name.\n"
                "Set your Flatpak terminal's command to /usr/bin/bash.") == EOF;
}
