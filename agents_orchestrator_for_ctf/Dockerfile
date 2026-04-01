ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm
ARG PROFILE_BASE_IMAGE=python:3.12-slim-bookworm
ARG PROFILE=base
ARG RADARE2_VERSION=5.9.8
ARG JADX_VERSION=1.5.2
ARG DEX2JAR_VERSION=2.4
ARG SMALI_VERSION=2.5.2
ARG DOTNET_CHANNEL=8.0
ARG WASM_TOOLS_VERSION=1.246.1

FROM ${PYTHON_BASE_IMAGE} AS base

ARG PROFILE=base

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=600
ENV PIP_PROGRESS_BAR=off
ENV PIP_ROOT_USER_ACTION=ignore
ENV TERM=xterm-256color
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV CTF_PROFILE=${PROFILE}
ENV CTF_TASK=/workspace/task
ENV CTF_ARTIFACTS=/workspace/artifacts
ENV CTF_TOOL_CACHE=/workspace/tool-cache
ENV CTF_BIN_DIR=/workspace/tool-cache/bin
ENV CTF_PYTHON_PREFIX=/workspace/tool-cache/python
ENV CTF_CARGO_ROOT=/workspace/tool-cache/.cargo-root
ENV CTF_CARGO_HOME=/workspace/tool-cache/.cargo-home
ENV CTF_GO_BIN=/workspace/tool-cache/bin
ENV CTF_GEM_HOME=/workspace/tool-cache/.gem
ENV CTF_NPM_PREFIX=/workspace/tool-cache/.npm-global
ENV DOTNET_ROOT=/opt/dotnet
ENV PYTHONPATH=/workspace/tool-cache/python/lib/python3.12/site-packages:/workspace/tool-cache/python/lib64/python3.12/site-packages
ENV PATH=/opt/ctf-profile-venv/bin:/opt/radare2/bin:/opt/mobile-tools/bin:/opt/wasm-tools/bin:/opt/dotnet:/opt/dotnet-tools/bin:/opt/ruby-gems/bin:/workspace/tool-cache/bin:/workspace/tool-cache/python/bin:/workspace/tool-cache/.cargo-root/bin:/workspace/tool-cache/.npm-global/bin:/workspace/tool-cache/.gem/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    base_packages=( \
      bash binutils binwalk ca-certificates curl file gdb less procps \
      python3-venv strace unzip wget xxd z3 \
    ); \
    apt-get update; \
    apt-get install -y --no-install-recommends "${base_packages[@]}"; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    python -m pip install --no-cache-dir --break-system-packages \
      --prefer-binary --retries 10 --timeout 600 \
      pwntools pycryptodome python-magic

COPY container/ctf-install /usr/local/bin/ctf-install
COPY container/ctf-tools /usr/local/bin/ctf-tools
RUN chmod +x /usr/local/bin/ctf-install /usr/local/bin/ctf-tools

WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS python-builder

ARG PROFILE

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    python -m venv --system-site-packages /opt/ctf-profile-venv; \
    pip=/opt/ctf-profile-venv/bin/pip; \
    case "${PROFILE}" in \
      base) profile_python_packages=(); profile_builder_packages=();; \
      web) profile_python_packages=(aiohttp beautifulsoup4 flask mitmproxy websocket-client websockets); profile_builder_packages=();; \
      privesc) profile_python_packages=(psutil pyroute2); profile_builder_packages=();; \
      pwn-userspace) profile_python_packages=(capstone keystone-engine ropper r2pipe unicorn); profile_builder_packages=(build-essential cmake);; \
      pwn-kernel) profile_python_packages=(capstone keystone-engine ropper unicorn); profile_builder_packages=(build-essential cmake);; \
      forensics-disk) profile_python_packages=(pillow); profile_builder_packages=();; \
      forensics-memory) profile_python_packages=(volatility3 yara-python); profile_builder_packages=();; \
      forensics-network) profile_python_packages=(impacket pyshark scapy); profile_builder_packages=();; \
      crypto) profile_python_packages=(gmpy2 sympy); profile_builder_packages=(build-essential libgmp-dev pkg-config python3-dev);; \
      crypto-heavy) profile_python_packages=(gmpy2 numpy sympy); profile_builder_packages=(build-essential libgmp-dev pkg-config python3-dev);; \
      reverse-static) profile_python_packages=(angr capstone keystone-engine pefile r2pipe ropper unicorn yara-python); profile_builder_packages=(build-essential cmake);; \
      reverse-dynamic) profile_python_packages=(angr capstone frida-tools keystone-engine pefile r2pipe ropper unicorn yara-python); profile_builder_packages=(build-essential cmake);; \
      reverse-mobile) profile_python_packages=(androguard frida-tools r2pipe); profile_builder_packages=();; \
      reverse-dotnet) profile_python_packages=(dnfile pefile); profile_builder_packages=();; \
      reverse-wasm) profile_python_packages=(wasmtime); profile_builder_packages=();; \
      stego-image) profile_python_packages=(opencv-python-headless pillow pyzbar); profile_builder_packages=();; \
      stego-audio) profile_python_packages=(numpy scipy); profile_builder_packages=();; \
      mobile) profile_python_packages=(androguard frida-tools); profile_builder_packages=();; \
      network) profile_python_packages=(impacket mitmproxy scapy); profile_builder_packages=();; \
      ppc) profile_python_packages=(numpy); profile_builder_packages=();; \
      game-hacking) profile_python_packages=(capstone frida-tools pefile unicorn); profile_builder_packages=();; \
      ai-ml) profile_python_packages=(jupyterlab matplotlib numpy onnx onnxruntime pandas scikit-learn scipy seaborn sentencepiece); profile_builder_packages=();; \
      *) echo "Unsupported PROFILE=${PROFILE}" >&2; exit 1;; \
    esac; \
    if [ "${#profile_builder_packages[@]}" -gt 0 ]; then \
      apt-get update; \
      apt-get install -y --no-install-recommends "${profile_builder_packages[@]}"; \
      rm -rf /var/lib/apt/lists/*; \
    fi; \
    if [ "${#profile_python_packages[@]}" -gt 0 ]; then \
      "${pip}" install --no-cache-dir --prefer-binary --retries 10 --timeout 600 "${profile_python_packages[@]}"; \
    fi; \
    case "${PROFILE}" in \
      ai-ml) \
        "${pip}" install --no-cache-dir --prefer-binary --retries 10 --timeout 600 \
          --index-url https://download.pytorch.org/whl/cpu \
          --extra-index-url https://pypi.org/simple \
          torch; \
        "${pip}" install --no-cache-dir --prefer-binary --retries 10 --timeout 600 transformers; \
        ;; \
      *) ;; \
    esac

FROM ${PROFILE_BASE_IMAGE} AS radare2-builder

ARG PROFILE
ARG RADARE2_VERSION

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    mkdir -p /opt/radare2; \
    case "${PROFILE}" in \
      pwn-userspace|pwn-kernel|reverse-static|reverse-dynamic|reverse-mobile|reverse-wasm|game-hacking) \
        apt-get update; \
        apt-get install -y --no-install-recommends build-essential curl git libcapstone-dev libssl-dev pkg-config; \
        mkdir -p /tmp/radare2; \
        curl --fail --location --retry 10 --retry-all-errors --retry-delay 3 \
          "https://github.com/radareorg/radare2/archive/refs/tags/${RADARE2_VERSION}.tar.gz" \
          -o /tmp/radare2.tar.gz; \
        tar -xzf /tmp/radare2.tar.gz -C /tmp/radare2 --strip-components=1; \
        cd /tmp/radare2; \
        sys/install.sh --without-pull --install --prefix=/opt/radare2; \
        find /opt/radare2 -type f -name '*.a' -delete; \
        rm -rf /tmp/radare2 /tmp/radare2.tar.gz /var/lib/apt/lists/*; \
        ;; \
      *) ;; \
    esac

FROM ${PROFILE_BASE_IMAGE} AS ruby-tools-builder

ARG PROFILE

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    mkdir -p /opt/ruby-gems; \
    case "${PROFILE}" in \
      pwn-userspace|pwn-kernel|reverse-dynamic) \
        apt-get update; \
        apt-get install -y --no-install-recommends build-essential ruby-full; \
        GEM_HOME=/opt/ruby-gems GEM_PATH=/opt/ruby-gems gem install --no-document one_gadget seccomp-tools; \
        rm -rf /var/lib/apt/lists/*; \
        ;; \
      *) ;; \
    esac

FROM ${PROFILE_BASE_IMAGE} AS mobile-tools-builder

ARG PROFILE
ARG JADX_VERSION
ARG DEX2JAR_VERSION
ARG SMALI_VERSION

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    mkdir -p /opt/mobile-tools/bin /opt/mobile-tools/jars; \
    case "${PROFILE}" in \
      reverse-mobile|mobile) \
        apt-get update; \
        apt-get install -y --no-install-recommends default-jre-headless unzip; \
        curl -fsSL "https://github.com/skylot/jadx/releases/download/v${JADX_VERSION}/jadx-${JADX_VERSION}.zip" -o /tmp/jadx.zip; \
        unzip -q /tmp/jadx.zip -d /opt/mobile-tools/jadx; \
        ln -sf /opt/mobile-tools/jadx/bin/jadx /opt/mobile-tools/bin/jadx; \
        ln -sf /opt/mobile-tools/jadx/bin/jadx-gui /opt/mobile-tools/bin/jadx-gui; \
        curl -fsSL "https://github.com/pxb1988/dex2jar/releases/download/v${DEX2JAR_VERSION}/dex-tools-v${DEX2JAR_VERSION}.zip" -o /tmp/dex2jar.zip; \
        unzip -q /tmp/dex2jar.zip -d /opt/mobile-tools/dex2jar; \
        find /opt/mobile-tools/dex2jar -type f -name '*.sh' -exec ln -sf {} /opt/mobile-tools/bin/ \;; \
        curl -fsSL "https://repo1.maven.org/maven2/org/smali/smali/${SMALI_VERSION}/smali-${SMALI_VERSION}.jar" -o /opt/mobile-tools/jars/smali.jar; \
        curl -fsSL "https://repo1.maven.org/maven2/org/smali/baksmali/${SMALI_VERSION}/baksmali-${SMALI_VERSION}.jar" -o /opt/mobile-tools/jars/baksmali.jar; \
        printf '#!/usr/bin/env bash\nexec java -jar /opt/mobile-tools/jars/smali.jar "$@"\n' > /opt/mobile-tools/bin/smali; \
        printf '#!/usr/bin/env bash\nexec java -jar /opt/mobile-tools/jars/baksmali.jar "$@"\n' > /opt/mobile-tools/bin/baksmali; \
        chmod +x /opt/mobile-tools/bin/smali /opt/mobile-tools/bin/baksmali; \
        rm -f /tmp/jadx.zip /tmp/dex2jar.zip; \
        rm -rf /var/lib/apt/lists/*; \
        ;; \
      *) ;; \
    esac

FROM ${PROFILE_BASE_IMAGE} AS dotnet-tools-builder

ARG PROFILE
ARG DOTNET_CHANNEL

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    mkdir -p /opt/dotnet /opt/dotnet-tools/bin; \
    case "${PROFILE}" in \
      reverse-dotnet) \
        curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh; \
        bash /tmp/dotnet-install.sh --channel "${DOTNET_CHANNEL}" --install-dir /opt/dotnet; \
        PATH="/opt/dotnet:${PATH}" DOTNET_ROOT=/opt/dotnet /opt/dotnet/dotnet tool install --tool-path /opt/dotnet-tools/bin ilspycmd; \
        rm -f /tmp/dotnet-install.sh; \
        ;; \
      *) ;; \
    esac

FROM ${PROFILE_BASE_IMAGE} AS wasm-tools-builder

ARG PROFILE
ARG WASM_TOOLS_VERSION

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN set -eux; \
    mkdir -p /opt/wasm-tools/bin; \
    case "${PROFILE}" in \
      reverse-wasm) \
        arch="$(dpkg --print-architecture)"; \
        case "${arch}" in \
          amd64) wasm_tools_arch=x86_64-linux;; \
          arm64) wasm_tools_arch=aarch64-linux;; \
          *) echo "Unsupported reverse-wasm architecture: ${arch}" >&2; exit 1;; \
        esac; \
        curl -fsSL "https://github.com/bytecodealliance/wasm-tools/releases/download/v${WASM_TOOLS_VERSION}/wasm-tools-${WASM_TOOLS_VERSION}-${wasm_tools_arch}.tar.gz" -o /tmp/wasm-tools.tar.gz; \
        mkdir -p /tmp/wasm-tools; \
        tar -xzf /tmp/wasm-tools.tar.gz -C /tmp/wasm-tools; \
        install -m 0755 /tmp/wasm-tools/wasm-tools-${WASM_TOOLS_VERSION}-${wasm_tools_arch}/wasm-tools /opt/wasm-tools/bin/wasm-tools; \
        export HOME=/tmp/wasm-home; \
        mkdir -p "${HOME}"; \
        curl -fsSL https://wasmtime.dev/install.sh | bash; \
        curl -fsSL https://get.wasmer.io | bash; \
        cp -a "${HOME}/.wasmtime/bin/." /opt/wasm-tools/bin/; \
        cp -a "${HOME}/.wasmer/bin/." /opt/wasm-tools/bin/; \
        rm -rf /tmp/wasm-tools /tmp/wasm-tools.tar.gz /tmp/wasm-home; \
        ;; \
      *) ;; \
    esac

FROM ${PROFILE_BASE_IMAGE} AS web
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends dnsutils dirb ffuf gobuster hydra netcat-openbsd nmap proxychains4 socat sqlmap telnet wfuzz whois; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS privesc
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends acl attr dnsutils iproute2 iputils-ping libcap-ng-utils libcap2-bin lsof net-tools netcat-openbsd nmap openssh-client psmisc socat sqlite3 sshpass sudo tmux uidmap util-linux whois; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS pwn-userspace
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=radare2-builder /opt/radare2 /opt/radare2
COPY --from=ruby-tools-builder /opt/ruby-gems /opt/ruby-gems
ENV GEM_HOME=/opt/ruby-gems
ENV GEM_PATH=/opt/ruby-gems
ENV LD_LIBRARY_PATH=/opt/radare2/lib
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential gdb-multiarch netcat-openbsd patchelf qemu-user qemu-user-static ruby-full socat; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS pwn-kernel
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=radare2-builder /opt/radare2 /opt/radare2
COPY --from=ruby-tools-builder /opt/ruby-gems /opt/ruby-gems
ENV GEM_HOME=/opt/ruby-gems
ENV GEM_PATH=/opt/ruby-gems
ENV LD_LIBRARY_PATH=/opt/radare2/lib
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential busybox cpio dwarves elfutils gdb-multiarch gdbserver kmod linux-perf netcat-openbsd patchelf qemu-system-arm qemu-system-misc qemu-system-x86 qemu-user qemu-user-static ruby-full socat; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS forensics-disk
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends cabextract foremost libimage-exiftool-perl p7zip-full pdfcrack qpdf sleuthkit testdisk tesseract-ocr zbar-tools; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS forensics-memory
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends gdb-multiarch lz4 p7zip-full; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS forensics-network
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends dnsutils net-tools nmap openssh-client smbclient socat tcpdump tcpflow telnet tshark whois ngrep; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS crypto
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends bc libgmp10 pari-gp sqlite3; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS crypto-heavy
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends bc libgmp10 pari-gp sagemath sqlite3; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS reverse-static
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=radare2-builder /opt/radare2 /opt/radare2
ENV LD_LIBRARY_PATH=/opt/radare2/lib
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends gdb-multiarch p7zip-full patchelf sqlite3 yara; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS reverse-dynamic
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=radare2-builder /opt/radare2 /opt/radare2
COPY --from=ruby-tools-builder /opt/ruby-gems /opt/ruby-gems
ENV GEM_HOME=/opt/ruby-gems
ENV GEM_PATH=/opt/ruby-gems
ENV LD_LIBRARY_PATH=/opt/radare2/lib
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends gdb-multiarch gdbserver patchelf qemu-user qemu-user-static ruby-full socat sqlite3 tmux yara; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS reverse-mobile
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=radare2-builder /opt/radare2 /opt/radare2
COPY --from=mobile-tools-builder /opt/mobile-tools /opt/mobile-tools
ENV LD_LIBRARY_PATH=/opt/radare2/lib
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends aapt adb apktool default-jre-headless p7zip-full sqlite3; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS reverse-dotnet
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=dotnet-tools-builder /opt/dotnet /opt/dotnet
COPY --from=dotnet-tools-builder /opt/dotnet-tools /opt/dotnet-tools
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends gdb-multiarch libicu72 mono-devel; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS reverse-wasm
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=radare2-builder /opt/radare2 /opt/radare2
COPY --from=wasm-tools-builder /opt/wasm-tools /opt/wasm-tools
ENV LD_LIBRARY_PATH=/opt/radare2/lib
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends binaryen wabt; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS stego-image
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends imagemagick libimage-exiftool-perl pngcheck steghide tesseract-ocr zbar-tools; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS stego-audio
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg flac lame sox steghide vorbis-tools; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS mobile
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=mobile-tools-builder /opt/mobile-tools /opt/mobile-tools
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends aapt adb apktool default-jre-headless p7zip-full sqlite3; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS network
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends default-mysql-client dnsutils inetutils-ftp net-tools netcat-openbsd nmap openssh-client postgresql-client redis-tools smbclient socat sqlite3 tcpdump telnet tshark whois; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS ppc
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential cargo clang default-jdk git golang-go nodejs npm php-cli pypy3 ruby-full sqlite3; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS game-hacking
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
COPY --from=radare2-builder /opt/radare2 /opt/radare2
ENV LD_LIBRARY_PATH=/opt/radare2/lib
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends cabextract gdb-multiarch mingw-w64 mono-devel p7zip-full patchelf wine64; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]

FROM ${PROFILE_BASE_IMAGE} AS ai-ml
COPY --from=python-builder /opt/ctf-profile-venv /opt/ctf-profile-venv
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends default-jdk graphviz sqlite3; \
    rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/task
CMD ["sleep", "infinity"]
