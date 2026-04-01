#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
PROFILES_DOC="${PROJECT_ROOT}/container/profiles.md"

read_profiles() {
  awk '
    /<!-- profiles:start -->/ { in_block=1; next }
    /<!-- profiles:end -->/ { in_block=0 }
    in_block && $0 ~ /^- `/ {
      match($0, /`[a-z0-9-]+`/)
      if (RSTART > 0) {
        print substr($0, RSTART + 1, RLENGTH - 2)
      }
    }
  ' "${PROFILES_DOC}"
}

run_smoke() {
  local profile="$1"
  case "${profile}" in
    base)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v python3 gdb binwalk strings xxd file curl wget strace z3 >/dev/null; python3 -c 'import pwn, Crypto'"
      ;;
    web)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v ffuf gobuster sqlmap wfuzz hydra nmap dirb proxychains4 socat >/dev/null; python3 -c 'import aiohttp, bs4, flask, mitmproxy, websockets, websocket'"
      ;;
    privesc)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v sudo ssh sshpass getcap setcap capsh getpcaps getfacl setfacl getfattr setfattr unshare nsenter setpriv ip ss lsof nmap socat tmux >/dev/null; python3 -c 'import psutil, pyroute2'"
      ;;
    pwn-userspace)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v gdb gdb-multiarch binwalk strings xxd file curl wget strace patchelf socat r2 one_gadget seccomp-tools >/dev/null; python3 -c 'import capstone, keystone, ropper, r2pipe, unicorn'"
      ;;
    pwn-kernel)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v gdb gdb-multiarch binwalk strings xxd file curl wget strace qemu-system-x86_64 qemu-system-arm cpio busybox gdbserver r2 one_gadget seccomp-tools >/dev/null; python3 -c 'import capstone, keystone, ropper, unicorn'"
      ;;
    forensics-disk)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v foremost exiftool pdfcrack qpdf fls testdisk tesseract zbarimg >/dev/null; python3 -c 'import PIL'"
      ;;
    forensics-memory)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v lz4 gdb-multiarch >/dev/null; python3 -c 'import volatility3, yara'"
      ;;
    forensics-network)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v tcpdump tshark ngrep tcpflow smbclient socat nmap >/dev/null; python3 -c 'import scapy, pyshark; import impacket'"
      ;;
    crypto)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v gp sqlite3 z3 >/dev/null; python3 -c 'import gmpy2, sympy'"
      ;;
    crypto-heavy)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v sage gp sqlite3 z3 >/dev/null; python3 -c 'import gmpy2, numpy, sympy'"
      ;;
    reverse-static)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v r2 yara >/dev/null; python3 -c 'import angr, capstone, keystone, pefile, r2pipe, ropper, unicorn, yara'"
      ;;
    reverse-dynamic)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v r2 yara gdbserver one_gadget seccomp-tools frida-ps >/dev/null; python3 -c 'import angr, capstone, frida, keystone, pefile, r2pipe, ropper, unicorn, yara'"
      ;;
    reverse-mobile)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v apktool jadx adb smali baksmali r2 >/dev/null; python3 -c 'import androguard, frida, r2pipe'"
      ;;
    reverse-dotnet)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v dotnet ilspycmd mono >/dev/null; python3 -c 'import dnfile, pefile'"
      ;;
    reverse-wasm)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v wasm2wat wasm-opt wasmtime wasmer wasm-tools r2 >/dev/null; python3 -c 'import wasmtime'"
      ;;
    stego-image)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v pngcheck steghide tesseract zbarimg identify >/dev/null; python3 -c 'import cv2, PIL; from pyzbar import pyzbar'"
      ;;
    stego-audio)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v ffmpeg sox steghide flac lame >/dev/null; python3 -c 'import numpy, scipy'"
      ;;
    mobile)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v apktool jadx adb smali baksmali >/dev/null; python3 -c 'import androguard, frida'"
      ;;
    network)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v nmap tcpdump smbclient redis-cli psql mysql ftp telnet tshark >/dev/null; python3 -c 'import scapy, impacket, mitmproxy'"
      ;;
    ppc)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v gcc clang go node npm php pypy3 ruby >/dev/null; python3 -c 'import numpy'"
      ;;
    game-hacking)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v wine64 x86_64-w64-mingw32-gcc mono r2 >/dev/null; python3 -c 'import capstone, frida, pefile, unicorn'"
      ;;
    ai-ml)
      docker run --rm "ctf-swarm:${profile}" bash -c "set -e; command -v jupyter-lab >/dev/null; python3 -c 'import jupyterlab, matplotlib, numpy, onnxruntime, pandas, scipy, seaborn, sklearn, torch, transformers; assert torch.version.cuda is None'"
      ;;
    *)
      echo "unknown profile: ${profile}" >&2
      return 1
      ;;
  esac
}

mapfile -t all_profiles < <(read_profiles)

if [ "$#" -gt 0 ]; then
  selected_profiles=("$@")
else
  selected_profiles=("${all_profiles[@]}")
fi

status=0

for profile in "${selected_profiles[@]}"; do
  if run_smoke "${profile}"; then
    printf '%s\tOK\n' "${profile}"
  else
    printf '%s\tFAIL\n' "${profile}"
    status=1
  fi
done

exit "${status}"
