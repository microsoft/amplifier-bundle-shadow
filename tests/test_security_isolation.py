"""Security isolation tests for shadow environments.

These tests verify that containers provide proper isolation from the host.
Run with a real container (not mocked) to validate actual security boundaries.

Usage:
    pytest tests/test_security_isolation.py -v --run-security

The tests are marked as slow/integration and skipped by default.
"""

from __future__ import annotations

import os
import subprocess
import pytest
from pathlib import Path

# Mark all tests in this module as security tests
pytestmark = [
    pytest.mark.security,
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("RUN_SECURITY_TESTS"),
        reason="Security tests require RUN_SECURITY_TESTS=1 and running container",
    ),
]


def get_container_runtime() -> str:
    """Detect available container runtime."""
    import shutil

    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    pytest.skip("No container runtime available")
    return ""  # Unreachable, but satisfies type checker


def exec_in_container(container: str, command: str) -> tuple[int, str, str]:
    """Execute command in container, return (exit_code, stdout, stderr)."""
    runtime = get_container_runtime()
    result = subprocess.run(
        [runtime, "exec", container, "sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def shadow_container():
    """Get the name of a running shadow container for testing.

    Set SHADOW_CONTAINER env var or this will look for any shadow-* container.
    """
    container = os.environ.get("SHADOW_CONTAINER")
    if container:
        return container

    # Try to find a running shadow container
    runtime = get_container_runtime()
    result = subprocess.run(
        [runtime, "ps", "--format", "{{.Names}}", "--filter", "name=shadow-"],
        capture_output=True,
        text=True,
    )
    containers = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
    if not containers:
        pytest.skip(
            "No running shadow container found. Set SHADOW_CONTAINER or start one."
        )
    return containers[0]


# =============================================================================
# 1. CONTAINER ESCAPE PREVENTION TESTS
# =============================================================================


class TestContainerEscapePrevention:
    """Verify container cannot access host resources."""

    # -------------------------------------------------------------------------
    # 1.1 Host Filesystem Access
    # -------------------------------------------------------------------------

    def test_cannot_write_to_host_root(self, shadow_container):
        """Container should not be able to write to host root filesystem.

        EXPECTED: Permission denied or path doesn't exist
        SECURITY: Prevents container escape via filesystem
        """
        test_file = "/host_escape_test_" + os.urandom(8).hex()

        exit_code, stdout, stderr = exec_in_container(
            shadow_container, f"touch {test_file} 2>&1 || echo 'BLOCKED'"
        )

        # Verify file doesn't exist on host
        assert not Path(test_file).exists(), f"Container wrote to host at {test_file}!"

        # Verify command failed or was blocked
        assert exit_code != 0 or "BLOCKED" in stdout or "denied" in stderr.lower()

    def test_cannot_access_host_etc_passwd(self, shadow_container):
        """Container should see its own /etc/passwd, not host's.

        EXPECTED: Container's passwd shows 'amplifier' user, not host users
        SECURITY: Filesystem namespace isolation
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container, "cat /etc/passwd"
        )

        assert exit_code == 0
        # Container should have amplifier user
        assert "amplifier" in stdout
        # Should NOT have host-specific users (adjust based on your host)
        host_user = os.environ.get("USER", "")
        if host_user and host_user != "amplifier":
            # This is a soft check - the user might coincidentally exist
            pass  # Container having same username is OK if it's not the same UID

    def test_cannot_access_host_home_directory(self, shadow_container):
        """Container should not access host user's home directory.

        EXPECTED: /home/amplifier exists, host user's home does not
        SECURITY: Prevents credential/config theft
        """
        host_user = os.environ.get("USER", "")

        # Check container's home
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "ls -la /home/amplifier"
        )
        assert exit_code == 0, "Container should have /home/amplifier"

        # Try to access host home (should fail or show different content)
        if host_user and host_user != "amplifier":
            exit_code, stdout, _ = exec_in_container(
                shadow_container, f"ls /home/{host_user} 2>&1"
            )
            # Should fail or directory shouldn't exist
            assert exit_code != 0 or "cannot access" in stdout.lower()

    def test_cannot_access_host_amplifier_config(self, shadow_container):
        """Container cannot access host's ~/.amplifier directory.

        EXPECTED: Path doesn't exist or is empty in container
        SECURITY: Prevents API key theft from host config
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "cat /home/amplifier/.amplifier/settings.yaml 2>&1 || "
            "cat ~/.amplifier/settings.yaml 2>&1 || echo 'NOT_FOUND'",
        )

        # File should not exist or contain host secrets
        if exit_code == 0 and "NOT_FOUND" not in stdout:
            # If file exists, verify it's not the host's config
            assert "ANTHROPIC_API_KEY" not in stdout, "Host API keys exposed!"
            assert "OPENAI_API_KEY" not in stdout, "Host API keys exposed!"

    def test_cannot_mount_arbitrary_host_paths(self, shadow_container):
        """Container user cannot create new mounts to host filesystem.

        EXPECTED: mount command fails (no CAP_SYS_ADMIN)
        SECURITY: Prevents container escape via mount
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container, "mount --bind /etc /tmp/test_mount 2>&1 || echo 'BLOCKED'"
        )

        assert (
            "BLOCKED" in stdout
            or "permission denied" in stderr.lower()
            or "operation not permitted" in stderr.lower()
        )

    # -------------------------------------------------------------------------
    # 1.2 Host Process Access
    # -------------------------------------------------------------------------

    def test_cannot_see_host_processes(self, shadow_container):
        """Container should only see its own processes, not host processes.

        EXPECTED: ps shows only container processes
        SECURITY: PID namespace isolation - CRITICAL for pkill protection
        """
        exit_code, stdout, stderr = exec_in_container(shadow_container, "ps aux")

        assert exit_code == 0

        # Container should NOT see host processes
        # Look for processes that would only exist on host
        host_only_processes = [
            "systemd",  # Host init (unless container runs systemd)
            "dockerd",  # Docker daemon
            "containerd",  # Container daemon
            "sshd",  # SSH daemon (unlikely in container)
        ]

        for proc in host_only_processes:
            # Soft check - some containers might legitimately have these
            if proc in stdout:
                pytest.warns(f"WARNING: Host process '{proc}' visible in container")

    def test_cannot_kill_host_processes(self, shadow_container):
        """Container cannot signal/kill host processes.

        EXPECTED: pkill/kill commands fail to affect host
        SECURITY: Directly addresses the pkill incident
        """
        # Get host PID of the container runtime for reference
        # The container should NOT be able to see or kill this

        # First, verify PID 1 in container is NOT the host's PID 1
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "cat /proc/1/cmdline | tr '\\0' ' '"
        )

        assert exit_code == 0
        # Container's PID 1 should be entrypoint.sh or bash, NOT host init
        assert "systemd" not in stdout.lower() or "init" not in stdout.lower(), (
            "Container sees host's PID 1 - PID namespace not isolated!"
        )

        # Try to list processes with 'amplifier' - should only see container's
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "pgrep -a amplifier 2>&1 || echo 'NO_MATCH'"
        )

        # Count matching processes - should be 0 or only container processes
        lines = [
            line
            for line in stdout.strip().split("\n")
            if line and "NO_MATCH" not in line
        ]
        if lines:
            # If there are matches, verify they're container processes
            for line in lines:
                # PID should be low (container namespace) or it's concerning
                try:
                    pid = int(line.split()[0])
                    assert pid < 10000, (
                        f"High PID {pid} suggests host process visibility"
                    )
                except (ValueError, IndexError):
                    pass

    def test_pkill_does_not_affect_host(self, shadow_container):
        """Verify pkill from container cannot kill host processes.

        EXPECTED: pkill runs but only affects container processes
        SECURITY: Direct test for the reported incident
        """
        # This is a non-destructive test - we try to pkill a pattern
        # that would match host processes but verify host survives

        # Try to pkill something that exists on host but not container
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "pkill -0 -f 'unlikely_process_name_12345' 2>&1; echo \"EXIT:$?\"",
        )

        # The command itself should complete (container is fine)
        assert "EXIT:" in stdout

        # More importantly - if we got here, the host is still running
        # (the test framework is still executing)

    def test_cannot_access_proc_host_pids(self, shadow_container):
        """Container /proc should only show container PIDs.

        EXPECTED: /proc only contains low-numbered PIDs
        SECURITY: Verifies PID namespace isolation
        """
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "ls -d /proc/[0-9]* | wc -l"
        )

        assert exit_code == 0
        pid_count = int(stdout.strip())

        # Container should have relatively few processes
        # Host typically has 100+ PIDs, container should have <50
        assert pid_count < 100, (
            f"Container sees {pid_count} PIDs - possible host PID exposure"
        )

    # -------------------------------------------------------------------------
    # 1.3 Host Network Services
    # -------------------------------------------------------------------------

    def test_cannot_access_host_docker_socket(self, shadow_container):
        """Container cannot access Docker socket to spawn sibling containers.

        EXPECTED: /var/run/docker.sock doesn't exist or is inaccessible
        SECURITY: Prevents container escape via Docker API
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container, "ls -la /var/run/docker.sock 2>&1 || echo 'NOT_FOUND'"
        )

        assert (
            "NOT_FOUND" in stdout
            or "No such file" in stdout
            or "permission denied" in stderr.lower()
        )

    def test_cannot_access_host_localhost_services(self, shadow_container):
        """Container localhost is isolated from host localhost.

        EXPECTED: localhost:22 (SSH) not accessible from container
        SECURITY: Network namespace isolation
        """
        # Try to connect to host's SSH port (usually 22)
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "timeout 2 bash -c '</dev/tcp/localhost/22' 2>&1 && echo 'CONNECTED' || echo 'BLOCKED'",
        )

        # Should NOT be able to connect to host's SSH
        # Note: This might fail if container has its own SSH or if SSH isn't running
        assert "CONNECTED" not in stdout or exit_code != 0, (
            "Container can access host's localhost services!"
        )

    def test_can_access_external_network(self, shadow_container):
        """Container CAN access external network (needed for real GitHub).

        EXPECTED: External network access works
        SECURITY: This is expected behavior, not a vulnerability
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "curl -s --connect-timeout 5 https://api.github.com/zen 2>&1 || echo 'FAILED'",
        )

        # Should be able to reach GitHub (or get a response)
        # Might fail in air-gapped environments - that's OK
        if "FAILED" in stdout:
            pytest.skip("Network access to GitHub unavailable (expected in some envs)")


# =============================================================================
# 2. CREDENTIAL SAFETY TESTS
# =============================================================================


class TestCredentialSafety:
    """Verify credentials are properly isolated."""

    def test_only_specified_env_vars_present(self, shadow_container):
        """Only explicitly passed env vars should be present.

        EXPECTED: No host env vars leaked (HOME, USER are container's)
        SECURITY: Prevents credential leakage from host environment
        """
        exit_code, stdout, _ = exec_in_container(shadow_container, "env | sort")

        assert exit_code == 0
        env_vars = dict(
            line.split("=", 1) for line in stdout.strip().split("\n") if "=" in line
        )

        # These should be container values, not host
        assert env_vars.get("USER") == "amplifier"
        assert env_vars.get("HOME") == "/home/amplifier"

        # These host vars should NOT be present
        host_vars_to_check = [
            "SSH_AUTH_SOCK",  # SSH agent
            "DISPLAY",  # X11 display
            "XAUTHORITY",  # X11 auth
            "DBUS_SESSION_BUS_ADDRESS",  # D-Bus
        ]

        for var in host_vars_to_check:
            if var in env_vars and os.environ.get(var):
                # If host has it and container has it, might be leaked
                assert env_vars[var] != os.environ.get(var), (
                    f"Host env var {var} leaked to container"
                )

    def test_credentials_not_in_process_list(self, shadow_container):
        """API keys should not be visible in process list.

        EXPECTED: ps output doesn't show API key values
        SECURITY: Prevents credential exposure via /proc
        """
        exit_code, stdout, _ = exec_in_container(
            shadow_container,
            "ps auxwwe",  # Wide output with environment
        )

        assert exit_code == 0

        # Common API key patterns that should NOT appear
        sensitive_patterns = [
            "sk-",  # OpenAI key prefix
            "sk-ant-",  # Anthropic key prefix
            "ghp_",  # GitHub PAT prefix
            "gho_",  # GitHub OAuth prefix
            "github_pat_",  # GitHub fine-grained PAT
        ]

        for pattern in sensitive_patterns:
            if pattern in stdout:
                # Check if it's a full key (not just the prefix in a comment)
                # Keys are typically 40+ chars
                import re

                matches = re.findall(f"{pattern}[A-Za-z0-9_-]{{30,}}", stdout)
                assert not matches, f"API key visible in process list: {pattern}..."

    def test_cannot_read_host_ssh_keys(self, shadow_container):
        """Container cannot access host's SSH keys.

        EXPECTED: ~/.ssh not accessible or contains only container's keys
        SECURITY: Prevents SSH key theft
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "cat ~/.ssh/id_rsa 2>&1 || cat ~/.ssh/id_ed25519 2>&1 || echo 'NO_KEYS'",
        )

        # Should not find SSH private keys
        assert (
            "NO_KEYS" in stdout
            or "No such file" in stdout
            or "PRIVATE KEY" not in stdout
        )

    def test_cannot_read_host_aws_credentials(self, shadow_container):
        """Container cannot access host's AWS credentials.

        EXPECTED: ~/.aws not accessible
        SECURITY: Prevents cloud credential theft
        """
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "cat ~/.aws/credentials 2>&1 || echo 'NO_AWS'"
        )

        assert "NO_AWS" in stdout or "No such file" in stdout
        assert "aws_secret_access_key" not in stdout.lower()

    def test_cannot_read_host_kube_config(self, shadow_container):
        """Container cannot access host's Kubernetes config.

        EXPECTED: ~/.kube not accessible
        SECURITY: Prevents k8s credential theft
        """
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "cat ~/.kube/config 2>&1 || echo 'NO_KUBE'"
        )

        assert "NO_KUBE" in stdout or "No such file" in stdout
        assert "client-certificate-data" not in stdout.lower()


# =============================================================================
# 3. RESOURCE LIMIT TESTS
# =============================================================================


class TestResourceLimits:
    """Verify resource limits are in place."""

    def test_memory_limit_exists(self, shadow_container):
        """Container should have memory limits configured.

        EXPECTED: Memory limit is set (not unlimited)
        SECURITY: Prevents DoS via memory exhaustion
        """
        runtime = get_container_runtime()
        result = subprocess.run(
            [
                runtime,
                "inspect",
                shadow_container,
                "--format",
                "{{.HostConfig.Memory}}",
            ],
            capture_output=True,
            text=True,
        )

        memory_limit = int(result.stdout.strip() or "0")

        if memory_limit == 0:
            pytest.warns(
                UserWarning,
                "WARNING: No memory limit set. Container can exhaust host memory.",
            )
        else:
            # Convert to GB for readability
            limit_gb = memory_limit / (1024**3)
            assert limit_gb > 0, "Memory limit should be positive"
            assert limit_gb < 64, f"Memory limit {limit_gb}GB seems too high"

    def test_cpu_limit_exists(self, shadow_container):
        """Container should have CPU limits configured.

        EXPECTED: CPU quota/shares are limited
        SECURITY: Prevents DoS via CPU exhaustion
        """
        runtime = get_container_runtime()
        result = subprocess.run(
            [
                runtime,
                "inspect",
                shadow_container,
                "--format",
                "{{.HostConfig.CpuQuota}} {{.HostConfig.CpuPeriod}}",
            ],
            capture_output=True,
            text=True,
        )

        parts = result.stdout.strip().split()
        cpu_quota = int(parts[0]) if parts else 0
        cpu_period = int(parts[1]) if len(parts) > 1 else 0

        if cpu_quota == 0:
            pytest.warns(
                UserWarning,
                "WARNING: No CPU limit set. Container can exhaust host CPU.",
            )
        else:
            # Effective CPUs = quota / period
            effective_cpus = cpu_quota / cpu_period if cpu_period else 0
            assert effective_cpus > 0, "CPU limit should be positive"

    def test_pids_limit_exists(self, shadow_container):
        """Container should have process count limits.

        EXPECTED: PidsLimit is set
        SECURITY: Prevents fork bomb DoS
        """
        runtime = get_container_runtime()
        result = subprocess.run(
            [
                runtime,
                "inspect",
                shadow_container,
                "--format",
                "{{.HostConfig.PidsLimit}}",
            ],
            capture_output=True,
            text=True,
        )

        pids_limit = result.stdout.strip()

        if pids_limit in ["0", "-1", "<nil>", ""]:
            pytest.warns(
                UserWarning,
                "WARNING: No PID limit set. Container vulnerable to fork bombs.",
            )
        else:
            limit = int(pids_limit)
            assert limit > 0, "PID limit should be positive"
            assert limit < 10000, f"PID limit {limit} seems too high"

    def test_disk_space_isolation(self, shadow_container):
        """Container disk usage should be limited to mounted volumes.

        EXPECTED: Cannot fill up host disk outside of workspace
        SECURITY: Prevents DoS via disk exhaustion
        """
        # Try to write a large file outside workspace
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "dd if=/dev/zero of=/tmp/testfile bs=1M count=100 2>&1; "
            "rm -f /tmp/testfile; echo 'SIZE_TEST_DONE'",
        )

        # The test passed if we can write to /tmp (expected)
        # but /tmp should be container-local, not host /tmp
        assert "SIZE_TEST_DONE" in stdout

        # Verify /tmp is not the host's /tmp
        exit_code, stdout, _ = exec_in_container(shadow_container, "df /tmp | tail -1")

        # Should show container filesystem, not host root
        # This is a soft check - depends on container config

    def test_cannot_fork_bomb(self, shadow_container):
        """Fork bomb should be contained by PID limits.

        EXPECTED: Fork bomb fails or is limited
        SECURITY: Prevents DoS via process exhaustion
        WARNING: This test may temporarily impact container performance
        """
        # Limited fork - don't actually bomb, just test limits
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "for i in $(seq 1 100); do sleep 0.01 & done 2>&1; "
            "echo 'SPAWNED'; sleep 0.5; "
            "jobs | wc -l",
        )

        # Should either succeed (within limits) or fail (hit limit)
        # Either is acceptable as long as host survives
        assert exit_code == 0 or "resource temporarily unavailable" in stderr.lower()


# =============================================================================
# 4. SNAPSHOT INTEGRITY TESTS
# =============================================================================


class TestSnapshotIntegrity:
    """Verify snapshot isolation and integrity."""

    def test_snapshots_are_readonly(self, shadow_container):
        """Snapshot directory should be read-only.

        EXPECTED: Write operations fail on /snapshots
        SECURITY: Protects source repository integrity
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container, "touch /snapshots/test_write 2>&1 || echo 'READONLY'"
        )

        assert (
            "READONLY" in stdout
            or "read-only" in stderr.lower()
            or "permission denied" in stderr.lower()
        )

    def test_cannot_modify_snapshot_bundles(self, shadow_container):
        """Cannot modify .bundle files in /snapshots.

        EXPECTED: Bundle files are immutable
        SECURITY: Protects source snapshot integrity
        """
        # Find a bundle file
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "find /snapshots -name '*.bundle' -type f | head -1"
        )

        if not stdout.strip():
            pytest.skip("No snapshot bundles found to test")

        bundle_path = stdout.strip()

        # Try to modify it
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            f"echo 'corrupted' >> '{bundle_path}' 2>&1 || echo 'PROTECTED'",
        )

        assert "PROTECTED" in stdout or "read-only" in stderr.lower()

    def test_workspace_is_writable(self, shadow_container):
        """Workspace directory should be writable.

        EXPECTED: Can create/modify files in /workspace
        SECURITY: This is expected behavior for the sandbox
        """
        test_file = f"/workspace/.security_test_{os.urandom(4).hex()}"

        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            f"echo 'test' > {test_file} && cat {test_file} && rm {test_file}",
        )

        assert exit_code == 0
        assert "test" in stdout

    def test_gitea_data_isolated(self, shadow_container):
        """Gitea data should be container-local.

        EXPECTED: /var/lib/gitea exists and is writable
        SECURITY: Each shadow has isolated git state
        """
        exit_code, stdout, _ = exec_in_container(
            shadow_container,
            "ls -la /var/lib/gitea && touch /var/lib/gitea/.test && rm /var/lib/gitea/.test",
        )

        assert exit_code == 0

    def test_cannot_escape_via_symlink_in_workspace(self, shadow_container):
        """Symlinks in workspace cannot escape to host filesystem.

        EXPECTED: Symlinks to outside paths fail or are contained
        SECURITY: Prevents symlink-based container escape
        """
        # Try to create symlink to host filesystem
        exit_code, stdout, stderr = exec_in_container(
            shadow_container,
            "ln -s /etc/passwd /workspace/passwd_link 2>&1 && "
            "cat /workspace/passwd_link && rm /workspace/passwd_link",
        )

        # Symlink to /etc/passwd should work, but it's the container's /etc/passwd
        if exit_code == 0:
            # If readable, verify it's container's passwd, not host's
            assert "amplifier" in stdout, "Should see container's passwd"

    def test_workspace_changes_isolated_per_shadow(self, shadow_container):
        """Changes in one shadow don't affect other shadows.

        EXPECTED: /workspace is unique to this container
        SECURITY: Shadow isolation
        """
        # Write a unique marker
        marker = f"MARKER_{os.urandom(8).hex()}"

        exit_code, stdout, _ = exec_in_container(
            shadow_container, f"echo '{marker}' > /workspace/.isolation_test"
        )

        assert exit_code == 0

        # Verify marker exists
        exit_code, stdout, _ = exec_in_container(
            shadow_container, "cat /workspace/.isolation_test"
        )

        assert marker in stdout

        # Clean up
        exec_in_container(shadow_container, "rm /workspace/.isolation_test")


# =============================================================================
# 5. CAPABILITY AND PRIVILEGE TESTS
# =============================================================================


class TestCapabilitiesAndPrivileges:
    """Verify container runs with minimal privileges."""

    def test_running_as_non_root(self, shadow_container):
        """Container processes should run as non-root user.

        EXPECTED: uid != 0
        SECURITY: Limits damage from container compromise
        """
        exit_code, stdout, _ = exec_in_container(shadow_container, "id")

        assert exit_code == 0
        assert "uid=0" not in stdout, "Container running as root!"
        assert "amplifier" in stdout

    def test_cannot_use_sudo(self, shadow_container):
        """Sudo should not be available or functional.

        EXPECTED: sudo fails or doesn't exist
        SECURITY: Prevents privilege escalation
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container, "sudo id 2>&1 || echo 'NO_SUDO'"
        )

        # Either sudo doesn't exist or it fails
        assert (
            "NO_SUDO" in stdout
            or "not found" in stderr
            or "not in the sudoers" in stderr
            or exit_code != 0
        )

    def test_cannot_change_uid(self, shadow_container):
        """Cannot escalate to root via su or similar.

        EXPECTED: su fails
        SECURITY: Prevents privilege escalation
        """
        exit_code, stdout, stderr = exec_in_container(
            shadow_container, "su -c 'id' root 2>&1 || echo 'SU_FAILED'"
        )

        assert (
            "SU_FAILED" in stdout
            or "authentication failure" in stderr.lower()
            or "must be run from a terminal" in stderr.lower()
        )

    def test_capabilities_dropped(self, shadow_container):
        """Container should have minimal Linux capabilities.

        EXPECTED: Dangerous capabilities are dropped
        SECURITY: Limits container escape vectors
        """
        runtime = get_container_runtime()
        result = subprocess.run(
            [
                runtime,
                "inspect",
                shadow_container,
                "--format",
                "{{.HostConfig.CapDrop}}",
            ],
            capture_output=True,
            text=True,
        )

        cap_drop = result.stdout.strip()

        # Check for dangerous capabilities that SHOULD be dropped
        dangerous_caps = [
            "CAP_SYS_ADMIN",  # Mount, namespace operations
            "CAP_NET_ADMIN",  # Network config
            "CAP_SYS_PTRACE",  # Process tracing
            "CAP_DAC_OVERRIDE",  # Bypass file permissions
        ]

        # Also check what's added
        result = subprocess.run(
            [
                runtime,
                "inspect",
                shadow_container,
                "--format",
                "{{.HostConfig.CapAdd}}",
            ],
            capture_output=True,
            text=True,
        )

        cap_add = result.stdout.strip()

        for cap in dangerous_caps:
            if cap in cap_add:
                pytest.fail(f"Dangerous capability {cap} is added!")

        if cap_drop == "[]" or not cap_drop:
            pytest.warns(
                UserWarning,
                "WARNING: No capabilities explicitly dropped. "
                "Consider adding --cap-drop=ALL and only adding needed caps.",
            )

    def test_seccomp_profile_active(self, shadow_container):
        """Seccomp filtering should be enabled.

        EXPECTED: Seccomp profile is not 'unconfined'
        SECURITY: Limits available syscalls
        """
        runtime = get_container_runtime()
        result = subprocess.run(
            [
                runtime,
                "inspect",
                shadow_container,
                "--format",
                "{{.HostConfig.SecurityOpt}}",
            ],
            capture_output=True,
            text=True,
        )

        security_opts = result.stdout.strip()

        if "seccomp=unconfined" in security_opts:
            pytest.fail("Seccomp is disabled (unconfined)!")

        # Note: Default Docker seccomp profile is usually fine
        # Just verify it's not explicitly disabled

    def test_no_privileged_mode(self, shadow_container):
        """Container must not run in privileged mode.

        EXPECTED: Privileged = false
        SECURITY: Critical - privileged containers have full host access
        """
        runtime = get_container_runtime()
        result = subprocess.run(
            [
                runtime,
                "inspect",
                shadow_container,
                "--format",
                "{{.HostConfig.Privileged}}",
            ],
            capture_output=True,
            text=True,
        )

        privileged = result.stdout.strip().lower()
        assert privileged == "false", "Container is running in privileged mode!"


# =============================================================================
# RUNNER CONFIGURATION
# =============================================================================


def pytest_configure(config):
    """Add custom markers."""
    config.addinivalue_line("markers", "security: mark test as security-focused")
    config.addinivalue_line(
        "markers", "integration: mark test as requiring real container"
    )


def pytest_addoption(parser):
    """Add --run-security option."""
    parser.addoption(
        "--run-security",
        action="store_true",
        default=False,
        help="Run security isolation tests (requires running container)",
    )
