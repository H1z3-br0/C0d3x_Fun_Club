# Docker Profiles

Единый источник истины для доступных Docker-профилей, которые понимают оркестратор и `build_profiles.sh`.

<!-- profiles:start -->
- `base`: Минимальный профиль по умолчанию с Python, debugger/tooling базой и крипто/pwn Python-библиотеками.
- `web`: HTTP/API exploitation, content discovery, SSRF, fuzzing, proxying и web reconnaissance.
- `privesc`: Linux post-exploitation после получения shell, sudo/SUID/capabilities, user pivot, ACL и локальная privilege escalation triage.
- `pwn-userspace`: ELF/userspace exploitation, heap/ROP, libc analysis, pwning и userspace emulation.
- `pwn-kernel`: Kernel exploitation, qemu-system, initramfs, cpio, kernel debugging и low-level helpers.
- `forensics-disk`: Disk image carving, filesystem analysis, metadata extraction и recovery tooling.
- `forensics-memory`: Memory dumps, volatility3, symbol-heavy triage и memory forensics workflows.
- `forensics-network`: PCAP, streams, protocol triage, packet inspection и network evidence extraction.
- `crypto`: Lightweight crypto/number theory tooling для классических CTF crypto задач.
- `crypto-heavy`: Расширенный math/solver профиль для тяжёлых crypto задач и symbolic/algebra workflows.
- `reverse-static`: Static reversing, disassembly, PE/ELF triage, binary patching и decompiler helpers.
- `reverse-dynamic`: Dynamic reversing, tracing, emulation, instrumentation и runtime analysis.
- `reverse-mobile`: Android reverse engineering без эмуляторов, APK/DEX triage, adb/frida tooling.
- `reverse-dotnet`: .NET/Mono reversing, IL inspection, managed binaries и CLR tooling.
- `reverse-wasm`: WebAssembly reversing, decompilation, runtime execution и wasm toolchains.
- `stego-image`: Image steganography, metadata, OCR, barcode/QR, format surgery и visual extraction.
- `stego-audio`: Audio steganography, spectral analysis, waveform conversion и codec tooling.
- `mobile`: Общий mobile/security профиль для Android app triage, adb/frida и app artifact workflows.
- `network`: Network services, recon, protocol probing, tunnels, sniffing и remote service interaction.
- `ppc`: Programming/problem-solving профиль с компиляторами, interpreters и algorithmic tooling.
- `game-hacking`: Memory scanners, packers, asset extraction, Wine helpers и game reverse tooling.
- `ai-ml`: CPU-only data science/ML профиль для model inspection, tensor workflows и notebook-style analysis.
<!-- profiles:end -->
