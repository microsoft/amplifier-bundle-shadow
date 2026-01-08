#!/usr/bin/env bash
#
# Shadow Environment Sandbox Setup Script
# 
# Sets up OS-level sandboxing prerequisites for amplifier-bundle-shadow.
# Supports: Ubuntu, WSL+Ubuntu, macOS
#
# Usage:
#   ./setup-sandbox.sh          # Interactive setup
#   ./setup-sandbox.sh --check  # Check current status only
#   ./setup-sandbox.sh --fix    # Attempt to fix issues automatically
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Detect platform
detect_platform() {
    local system
    system=$(uname -s)
    
    case "$system" in
        Linux)
            if grep -qi microsoft /proc/version 2>/dev/null; then
                echo "wsl"
            elif [ -f /etc/os-release ]; then
                # shellcheck source=/dev/null
                . /etc/os-release
                case "$ID" in
                    ubuntu|debian|pop) echo "ubuntu" ;;
                    fedora|rhel|centos) echo "fedora" ;;
                    arch|manjaro) echo "arch" ;;
                    *) echo "linux-other" ;;
                esac
            else
                echo "linux-other"
            fi
            ;;
        Darwin)
            echo "macos"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

# Print status messages
info() { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check if running as root
check_not_root() {
    if [ "$(id -u)" -eq 0 ]; then
        error "Do not run this script as root. It will use sudo when needed."
        exit 1
    fi
}

# ============================================================================
# Linux (Ubuntu/Debian) Setup
# ============================================================================

check_bubblewrap_installed() {
    if command -v bwrap &>/dev/null; then
        local version
        version=$(bwrap --version 2>/dev/null | head -1)
        success "Bubblewrap installed: $version"
        return 0
    else
        error "Bubblewrap not installed"
        return 1
    fi
}

install_bubblewrap_ubuntu() {
    info "Installing bubblewrap..."
    sudo apt-get update -qq
    sudo apt-get install -y bubblewrap
    success "Bubblewrap installed"
}

check_uidmap_installed() {
    if command -v newuidmap &>/dev/null && command -v newgidmap &>/dev/null; then
        success "uidmap (newuidmap/newgidmap) installed"
        return 0
    else
        error "uidmap not installed"
        return 1
    fi
}

install_uidmap_ubuntu() {
    info "Installing uidmap..."
    sudo apt-get update -qq
    sudo apt-get install -y uidmap
    success "uidmap installed"
}

check_subuid_subgid() {
    local user
    user=$(whoami)
    
    if grep -q "^${user}:" /etc/subuid 2>/dev/null && grep -q "^${user}:" /etc/subgid 2>/dev/null; then
        success "subuid/subgid configured for $user"
        return 0
    else
        error "subuid/subgid not configured for $user"
        return 1
    fi
}

setup_subuid_subgid() {
    local user
    user=$(whoami)
    
    info "Setting up subuid/subgid for $user..."
    sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$user"
    success "subuid/subgid configured"
}

check_userns_sysctl() {
    local value
    
    # Check unprivileged_userns_clone (older kernels)
    if [ -f /proc/sys/kernel/unprivileged_userns_clone ]; then
        value=$(cat /proc/sys/kernel/unprivileged_userns_clone)
        if [ "$value" = "1" ]; then
            success "kernel.unprivileged_userns_clone = 1"
        else
            error "kernel.unprivileged_userns_clone = $value (should be 1)"
            return 1
        fi
    fi
    
    # Check max_user_namespaces
    if [ -f /proc/sys/user/max_user_namespaces ]; then
        value=$(cat /proc/sys/user/max_user_namespaces)
        if [ "$value" -gt 0 ]; then
            success "user.max_user_namespaces = $value"
        else
            error "user.max_user_namespaces = $value (should be > 0)"
            return 1
        fi
    fi
    
    return 0
}

fix_userns_sysctl() {
    info "Enabling unprivileged user namespaces..."
    
    if [ -f /proc/sys/kernel/unprivileged_userns_clone ]; then
        echo 1 | sudo tee /proc/sys/kernel/unprivileged_userns_clone > /dev/null
        # Make persistent
        echo "kernel.unprivileged_userns_clone = 1" | sudo tee /etc/sysctl.d/90-userns.conf > /dev/null
    fi
    
    success "User namespace sysctl configured"
}

check_apparmor_userns() {
    if [ -f /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]; then
        local value
        value=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)
        if [ "$value" = "0" ]; then
            success "AppArmor userns restriction disabled"
            return 0
        else
            error "AppArmor restricts unprivileged userns (value=$value)"
            return 1
        fi
    else
        success "AppArmor userns restriction not present"
        return 0
    fi
}

fix_apparmor_userns() {
    if [ ! -f /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]; then
        return 0
    fi
    
    info "Configuring AppArmor to allow unprivileged user namespaces..."
    
    # Create AppArmor profile for bwrap
    sudo tee /etc/apparmor.d/bwrap > /dev/null << 'EOF'
# AppArmor profile for bubblewrap to allow user namespaces
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
EOF
    
    # Load the profile
    if command -v apparmor_parser &>/dev/null; then
        sudo apparmor_parser -r /etc/apparmor.d/bwrap 2>/dev/null || true
    fi
    
    # Also set the sysctl (belt and suspenders)
    echo 0 | sudo tee /proc/sys/kernel/apparmor_restrict_unprivileged_userns > /dev/null
    
    # Make sysctl persistent
    echo "kernel.apparmor_restrict_unprivileged_userns = 0" | sudo tee /etc/sysctl.d/90-apparmor-userns.conf > /dev/null
    
    success "AppArmor configured for bubblewrap"
}

check_bubblewrap_works() {
    info "Testing bubblewrap functionality..."
    if bwrap --dev-bind / / true 2>/dev/null; then
        success "Bubblewrap works correctly!"
        return 0
    else
        error "Bubblewrap test failed"
        return 1
    fi
}

# ============================================================================
# WSL-specific Setup
# ============================================================================

check_wsl_userns() {
    # WSL2 generally supports user namespaces, but WSL1 doesn't
    if [ -f /proc/sys/kernel/osrelease ]; then
        local release
        release=$(cat /proc/sys/kernel/osrelease 2>/dev/null || uname -r)
        if echo "$release" | grep -qi "microsoft"; then
            if echo "$release" | grep -qi "WSL2"; then
                success "Running on WSL2 (user namespaces supported)"
                return 0
            else
                warn "Appears to be WSL1 - user namespaces may not work"
                warn "Consider upgrading to WSL2: wsl --set-version <distro> 2"
                return 1
            fi
        fi
    fi
    return 0
}

# ============================================================================
# macOS Setup
# ============================================================================

check_macos_sandbox() {
    if command -v sandbox-exec &>/dev/null; then
        success "sandbox-exec available (built into macOS)"
        return 0
    else
        error "sandbox-exec not found"
        return 1
    fi
}

setup_macos() {
    info "Checking macOS sandbox capabilities..."
    
    if ! check_macos_sandbox; then
        error "sandbox-exec should be built into macOS. Something is wrong with your system."
        return 1
    fi
    
    # Test sandbox-exec
    info "Testing sandbox-exec..."
    if sandbox-exec -p '(version 1)(allow default)' /bin/echo "test" &>/dev/null; then
        success "sandbox-exec works correctly"
    else
        warn "sandbox-exec test failed - may need Full Disk Access in System Preferences"
    fi
    
    success "macOS sandbox setup complete"
}

# ============================================================================
# Main Setup Functions
# ============================================================================

setup_linux() {
    local platform=$1
    local fix_mode=${2:-false}
    local all_ok=true
    
    echo ""
    info "=== Linux Sandbox Setup ($platform) ==="
    echo ""
    
    # 1. Bubblewrap
    if ! check_bubblewrap_installed; then
        all_ok=false
        if [ "$fix_mode" = true ]; then
            case "$platform" in
                ubuntu|wsl) install_bubblewrap_ubuntu ;;
                fedora) sudo dnf install -y bubblewrap ;;
                arch) sudo pacman -S --noconfirm bubblewrap ;;
                *) error "Please install bubblewrap manually" ;;
            esac
        fi
    fi
    
    # 2. uidmap
    if ! check_uidmap_installed; then
        all_ok=false
        if [ "$fix_mode" = true ]; then
            case "$platform" in
                ubuntu|wsl) install_uidmap_ubuntu ;;
                fedora) sudo dnf install -y shadow-utils ;;
                arch) sudo pacman -S --noconfirm shadow ;;
                *) error "Please install uidmap/shadow-utils manually" ;;
            esac
        fi
    fi
    
    # 3. subuid/subgid
    if ! check_subuid_subgid; then
        all_ok=false
        if [ "$fix_mode" = true ]; then
            setup_subuid_subgid
        fi
    fi
    
    # 4. sysctl settings
    if ! check_userns_sysctl; then
        all_ok=false
        if [ "$fix_mode" = true ]; then
            fix_userns_sysctl
        fi
    fi
    
    # 5. AppArmor (Ubuntu-specific)
    if [ "$platform" = "ubuntu" ] || [ "$platform" = "wsl" ]; then
        if ! check_apparmor_userns; then
            all_ok=false
            if [ "$fix_mode" = true ]; then
                fix_apparmor_userns
            fi
        fi
    fi
    
    # 6. WSL-specific
    if [ "$platform" = "wsl" ]; then
        check_wsl_userns || all_ok=false
    fi
    
    # 7. Final test
    echo ""
    if check_bubblewrap_works; then
        echo ""
        success "=== All sandbox prerequisites satisfied! ==="
        echo ""
        echo "Available sandbox backend: bubblewrap"
        return 0
    else
        echo ""
        if [ "$all_ok" = false ]; then
            warn "Some prerequisites are missing. Run with --fix to attempt automatic fixes."
        else
            error "Bubblewrap installed but not working. Check kernel/security settings."
        fi
        echo ""
        echo "Fallback: 'direct' mode will be used (less isolation)"
        return 1
    fi
}

# ============================================================================
# Entry Point
# ============================================================================

main() {
    local mode="check"
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --check) mode="check" ;;
            --fix) mode="fix" ;;
            --help|-h)
                echo "Usage: $0 [--check|--fix]"
                echo ""
                echo "Options:"
                echo "  --check  Check sandbox prerequisites (default)"
                echo "  --fix    Attempt to fix issues automatically"
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                exit 1
                ;;
        esac
        shift
    done
    
    check_not_root
    
    local platform
    platform=$(detect_platform)
    
    echo ""
    echo "=========================================="
    echo " Shadow Environment Sandbox Setup"
    echo "=========================================="
    echo ""
    info "Detected platform: $platform"
    
    case "$platform" in
        ubuntu|wsl|fedora|arch|linux-other)
            setup_linux "$platform" "$( [ "$mode" = "fix" ] && echo true || echo false )"
            ;;
        macos)
            setup_macos
            ;;
        *)
            error "Unsupported platform: $platform"
            exit 1
            ;;
    esac
}

main "$@"
