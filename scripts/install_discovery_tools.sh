#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="${ROOT_DIR}/.tools"
BIN_DIR="${TOOLS_DIR}/bin"
GO_BIN_DIR="${TOOLS_DIR}/go/bin"

export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"

mkdir -p "${BIN_DIR}" "${GO_BIN_DIR}"

if ! command -v go >/dev/null 2>&1; then
  echo "go is required to install katana, gau, waybackurls, and hakrawler." >&2
  echo "Install Go first, then rerun this script." >&2
  exit 1
fi

export GOBIN="${GO_BIN_DIR}"

go install github.com/projectdiscovery/katana/cmd/katana@latest
go install github.com/lc/gau/v2/cmd/gau@latest
go install github.com/tomnomnom/waybackurls@latest
go install github.com/hakluke/hakrawler@latest

if [ ! -d "${TOOLS_DIR}/Sublist3r/.git" ]; then
  git clone --depth 1 https://github.com/aboul3la/Sublist3r.git "${TOOLS_DIR}/Sublist3r"
fi

if [ ! -x "${TOOLS_DIR}/sublist3r-venv/bin/python" ]; then
  python3 -m venv "${TOOLS_DIR}/sublist3r-venv"
fi
"${TOOLS_DIR}/sublist3r-venv/bin/python" -m pip install --upgrade pip
if [ -f "${TOOLS_DIR}/Sublist3r/requirements.txt" ]; then
  "${TOOLS_DIR}/sublist3r-venv/bin/python" -m pip install -r "${TOOLS_DIR}/Sublist3r/requirements.txt"
fi

cat > "${BIN_DIR}/sublist3r" <<EOF
#!/usr/bin/env bash
"${TOOLS_DIR}/sublist3r-venv/bin/python" "${TOOLS_DIR}/Sublist3r/sublist3r.py" "\$@"
EOF
chmod +x "${BIN_DIR}/sublist3r"

for tool in katana gau waybackurls hakrawler; do
  ln -sf "${GO_BIN_DIR}/${tool}" "${BIN_DIR}/${tool}"
done

echo "Discovery tools installed in ${TOOLS_DIR}."
echo "The application already searches .tools/bin and .tools/go/bin automatically."
