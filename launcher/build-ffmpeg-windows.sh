#!/bin/sh
set -eu

expected_fingerprint='FCF986EA15E6E293A5644F10B4322F04D67658D8'
source_archive='/input/ffmpeg-7.1.1.tar.xz'
source_signature='/input/ffmpeg-7.1.1.tar.xz.asc'

export GNUPGHOME='/tmp/ffmpeg-gnupg'
mkdir -m 0700 "$GNUPGHOME" /output
gpg --batch --quiet --import /input/ffmpeg-devel.asc
actual_fingerprint="$(
  gpg --batch --with-colons --fingerprint \
    | awk -F: '$1 == "fpr" { print $10; exit }'
)"
if [ "$actual_fingerprint" != "$expected_fingerprint" ]; then
  echo "Unexpected FFmpeg release-key fingerprint: $actual_fingerprint" >&2
  exit 1
fi
gpg --batch --verify "$source_signature" "$source_archive"

tar -xJf "$source_archive"
cd /build/ffmpeg-7.1.1

./configure \
  --prefix=/opt/ffmpeg-windows \
  --target-os=mingw32 \
  --arch=x86_64 \
  --cpu=x86-64 \
  --cross-prefix=x86_64-w64-mingw32- \
  --host-cc=gcc \
  --pkg-config=false \
  --extra-version=bili-workspace \
  --disable-autodetect \
  --enable-mediafoundation \
  --disable-doc \
  --disable-debug \
  --disable-network \
  --disable-shared \
  --enable-static \
  --disable-pthreads \
  --enable-w32threads \
  --disable-ffplay \
  --disable-ffprobe \
  --disable-postproc

make -j"$(getconf _NPROCESSORS_ONLN)"
x86_64-w64-mingw32-strip ffmpeg.exe

cp ffmpeg.exe /output/ffmpeg.exe
cp LICENSE.md /output/LICENSE.md
cp COPYING.LGPLv2.1 /output/COPYING.LGPLv2.1
sed -n 's/^FFMPEG_CONFIGURATION=//p' ffbuild/config.mak > /output/buildconf.txt
dpkg-query -W -f='${Package}=${Version}\n' \
  ca-certificates gcc gcc-mingw-w64-x86-64 gnupg libc6-dev make nasm pkg-config xz-utils \
  | LC_ALL=C sort > /output/toolchain-packages.txt
x86_64-w64-mingw32-objdump -p ffmpeg.exe \
  | sed -n 's/^[[:space:]]*DLL Name: //p' \
  | LC_ALL=C sort -u > /output/pe-imports.txt

test -s /output/ffmpeg.exe
test -s /output/LICENSE.md
test -s /output/COPYING.LGPLv2.1
test -s /output/buildconf.txt
test -s /output/toolchain-packages.txt
test -s /output/pe-imports.txt
