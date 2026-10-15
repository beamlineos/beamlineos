#!/usr/bin/sh
# SPDX-License-Identifier: MIT
# Exercise the independent development environment in P0, including execution of its output.
set -eu
fail() {
    status=$?
    [ "$status" = 0 ] || echo BEAMLINE_DEVEL_FAILED
}
trap fail EXIT
read -r context < /proc/self/attr/current || [ -n "$context" ]
case "$context" in user_u:user_r:user_t:*) ;; *) exit 1 ;; esac
if [ -r "${CREDENTIALS_DIRECTORY:-}/beamline.test.combo" ]; then
    # ci/test-combos: posix-devel next to the merged desktop (and possibly posix, printing).
    test -e /usr/lib/extension-release.d/extension-release.desktop-gnome
else
    # ci/test-devel: posix-devel over the base alone.
    test ! -e /run/extensions/posix.raw
    test ! -e /run/extensions/desktop-gnome.raw
    test ! -e /usr/lib/extension-release.d/extension-release.posix
    test ! -e /usr/lib/extension-release.d/extension-release.desktop-gnome
    test ! -e /usr/bin/gnome-shell
fi
test -e /usr/lib/extension-release.d/extension-release.posix-devel
work=$(mktemp -d /tmp/beamline-devel.XXXXXX)
export HOME="$work/home" XDG_CACHE_HOME="$work/cache"
mkdir -p "$HOME" "$XDG_CACHE_HOME"
cd "$work"
cat > answer.c <<'EOF'
#if __STDC_VERSION__ != 201710L
#error c17 must select C17
#endif
int answer(void) { return 42; }
EOF
cat > main.c <<'EOF'
#include <stdio.h>
#include <systemd/sd-id128.h>
int answer(void);
int main(void) { printf("%d\n", answer()); return answer() != 42; }
EOF
c17 -g -c answer.c
ar rcs libanswer.a answer.o
nm libanswer.a | grep ' answer$'
strip --strip-debug answer.o
cat > Makefile <<'EOF'
all: hello
hello: main.c libanswer.a
	c17 -g main.c libanswer.a -o hello
EOF
make
test "$(./hello)" = 42
# This non-login service has no activated home; debug the ELF directly.
gdb --batch -ex 'set startup-with-shell off' -ex 'file hello' -ex run > debugger.log 2>&1 || { cat debugger.log; exit 1; }
grep 'exited normally' debugger.log
ctags -f tags answer.c
grep '^answer[[:space:]]' tags
printf 'gettext("Beamline developer test");\n' > messages.c
xgettext --language=C --from-code=UTF-8 -o messages.po messages.c
grep 'Beamline developer test' messages.po
cat > parser.y <<'EOF'
%{
#include <stdio.h>
int yylex(void);
void yyerror(const char *);
%}
%token NUMBER
%%
input: NUMBER '\n' { if ($1 != 42) YYABORT; };
%%
void yyerror(const char *s) { fprintf(stderr, "%s\n", s); }
int main(void) { return yyparse(); }
EOF
cat > scanner.l <<'EOF'
%{
#include "y.tab.h"
#include <stdlib.h>
%}
%option noyywrap
%%
[0-9]+ { yylval = atoi(yytext); return NUMBER; }
\n return '\n';
[ \t]+ ;
. return yytext[0];
%%
EOF
yacc -d parser.y
lex -t scanner.l > lex.yy.c
c17 -D_POSIX_C_SOURCE=200809L y.tab.c lex.yy.c -o parser
printf '42\n' | ./parser
printf '#include <vector>\nint main() { std::vector<int> v{42}; return v[0] != 42; }\n' > cpp.cpp
g++ -std=c++17 cpp.cpp -o cpp
./cpp
cat > meson.build <<'EOF'
project('beamline-devel', 'c', default_options: ['c_std=c17'])
executable('hello-meson', ['main.c', 'answer.c'])
EOF
meson setup build
ninja -C build
test "$(./build/hello-meson)" = 42
pkg-config --exists libsystemd
cd /
rm -rf "$work"
echo BEAMLINE_DEVEL_OK
