"""Tests for deployment configuration files."""

import configparser
import pathlib
import re

import pytest

DEPLOY_DIR = pathlib.Path(__file__).resolve().parents[2] / "deploy"


class TestNhcService:
    """Validate nhc.service systemd unit."""

    @pytest.fixture()
    def unit(self):
        return (DEPLOY_DIR / "nhc.service").read_text()

    def test_file_exists(self):
        assert (DEPLOY_DIR / "nhc.service").is_file()

    def test_requires_docker(self, unit):
        assert "Requires=docker.service" in unit

    def test_restart_policy(self, unit):
        assert "Restart=always" in unit

    def test_nhc_bind_variable(self, unit):
        """NHC_BIND must default to 0.0.0.0 and be used in --publish."""
        assert "NHC_BIND=0.0.0.0" in unit
        assert "${NHC_BIND}:8080:8080" in unit

    def test_override_comment(self, unit):
        """Service must document the override location."""
        assert "override" in unit.lower()


class TestDuckdnsService:
    """Validate duckdns-update.service systemd unit."""

    @pytest.fixture()
    def unit(self):
        return (DEPLOY_DIR / "duckdns-update.service").read_text()

    def test_file_exists(self):
        assert (DEPLOY_DIR / "duckdns-update.service").is_file()

    def test_oneshot_type(self, unit):
        assert "Type=oneshot" in unit

    def test_uses_duckdns_api(self, unit):
        assert "duckdns.org/update" in unit

    def test_uses_env_vars(self, unit):
        assert "${DUCKDNS_SUBDOMAIN}" in unit
        assert "${DUCKDNS_TOKEN}" in unit


class TestDuckdnsTimer:
    """Validate duckdns-update.timer systemd unit."""

    @pytest.fixture()
    def unit(self):
        return (DEPLOY_DIR / "duckdns-update.timer").read_text()

    def test_file_exists(self):
        assert (DEPLOY_DIR / "duckdns-update.timer").is_file()

    def test_periodic_interval(self, unit):
        assert "OnUnitActiveSec=" in unit

    def test_install_target(self, unit):
        assert "WantedBy=timers.target" in unit


class TestSetupScript:
    """Validate deploy/setup.sh structure."""

    @pytest.fixture()
    def script(self):
        return (DEPLOY_DIR / "setup.sh").read_text()

    def test_file_exists(self):
        assert (DEPLOY_DIR / "setup.sh").is_file()

    def test_executable(self):
        path = DEPLOY_DIR / "setup.sh"
        assert path.stat().st_mode & 0o111, "setup.sh must be executable"

    def test_has_shebang(self, script):
        assert script.startswith("#!/")

    def test_set_euo_pipefail(self, script):
        assert "set -euo pipefail" in script

    def test_root_check(self, script):
        assert "EUID" in script

    def test_docker_check(self, script):
        assert "docker" in script

    def test_caddy_installation_debian(self, script):
        """Script must support Caddy install via apt-get."""
        assert "apt-get install -y caddy" in script

    def test_caddy_installation_arch(self, script):
        """Script must support Caddy install via pacman."""
        assert "pacman" in script and "caddy" in script

    def test_caddyfile_generation(self, script):
        """Script must write a Caddyfile with reverse_proxy."""
        assert "reverse_proxy localhost:8080" in script

    def test_csp_img_src_allows_blob(self, script):
        """CSP must allow blob: images.

        The Phase 5 PNG floor path fetches the rasterised floor and
        loads it via ``URL.createObjectURL`` (a ``blob:`` URL). An
        ``img-src`` directive without ``blob:`` blocks the floor and
        leaves the player on a blank screen.
        """
        match = re.search(r"img-src ([^;\"]+)", script)
        assert match, "no img-src directive found in setup.sh CSP"
        assert "blob:" in match.group(1), (
            f"img-src must include blob:, got: {match.group(1)!r}"
        )

    def test_duckdns_timer_install(self, script):
        """Script must install the DuckDNS timer."""
        assert "duckdns-update.timer" in script

    def test_caddy_validate(self, script):
        """Script must validate Caddyfile before restarting."""
        assert "caddy validate" in script

    def test_bind_localhost_with_caddy(self, script):
        """When DuckDNS is configured, Docker must bind to 127.0.0.1."""
        assert 'NHC_BIND="127.0.0.1"' in script

    def test_update_mode(self, script):
        assert "--update" in script

    def test_health_check(self, script):
        assert "/health" in script

    def test_override_permissions(self, script):
        """Override files with secrets must have restricted perms."""
        assert "chmod 600" in script


class TestCaddyfileTemplate:
    """Validate the docker-compose Caddyfile template at repo root.

    Kept byte-for-byte in sync with the CSP that setup.sh writes to
    ``/etc/caddy/Caddyfile`` so compose and host deployments share the
    same security posture.
    """

    @pytest.fixture()
    def caddyfile(self):
        return (DEPLOY_DIR.parent / "Caddyfile").read_text()

    def test_file_exists(self):
        assert (DEPLOY_DIR.parent / "Caddyfile").is_file()

    def test_csp_img_src_allows_blob(self, caddyfile):
        """CSP must allow blob: images (Phase 5 PNG floor path)."""
        match = re.search(r"img-src ([^;\"]+)", caddyfile)
        assert match, "no img-src directive found in Caddyfile CSP"
        assert "blob:" in match.group(1), (
            f"img-src must include blob:, got: {match.group(1)!r}"
        )

    def test_csp_script_src_allows_wasm_eval(self, caddyfile):
        """CSP must allow WASM instantiation (NIR/WASM floor path)."""
        match = re.search(r"script-src ([^;\"]+)", caddyfile)
        assert match, "no script-src directive found in Caddyfile CSP"
        assert "'wasm-unsafe-eval'" in match.group(1), (
            f"script-src must include 'wasm-unsafe-eval', "
            f"got: {match.group(1)!r}"
        )


class TestDockerfileBase:
    """Validate Dockerfile.base carries the WASM build toolchain.

    The app stage builds the browser wasm bundle with wasm-pack, so
    the base image must ship wasm-pack and the wasm32 Rust target.
    Changing this file forces an ``update.sh --base`` rebuild.
    """

    @pytest.fixture()
    def base(self):
        return (DEPLOY_DIR.parent / "Dockerfile.base").read_text()

    def test_file_exists(self):
        assert (DEPLOY_DIR.parent / "Dockerfile.base").is_file()

    def test_installs_wasm32_target(self, base):
        assert "rustup target add wasm32-unknown-unknown" in base

    def test_installs_wasm_pack(self, base):
        assert "wasm-pack" in base, "base image must install wasm-pack"


class TestDockerfile:
    """Validate the app-stage Dockerfile builds + serves WASM."""

    @pytest.fixture()
    def dockerfile(self):
        return (DEPLOY_DIR.parent / "Dockerfile").read_text()

    def test_file_exists(self):
        assert (DEPLOY_DIR.parent / "Dockerfile").is_file()

    def test_builds_wasm_bundle(self, dockerfile):
        """App stage must run wasm-pack so /wasm/ has a bundle."""
        assert "wasm-pack build crates/nhc-render-wasm" in dockerfile

    def test_render_mode_is_wasm(self, dockerfile):
        """Production defaults to the browser-side WASM floor path."""
        assert "ENV NHC_RENDER_MODE=wasm" in dockerfile
