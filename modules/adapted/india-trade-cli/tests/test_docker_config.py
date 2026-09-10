from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""
Tests for Docker deployment configuration (#162).
Validates that docker-compose files and Dockerfile are well-formed.
"""


from pathlib import Path

DOCKER_DIR = Path(__file__).parent.parent / "docker"


class TestDockerComposeConfig:
    def test_docker_compose_exists(self):
        assert (DOCKER_DIR / "docker-compose.yml").exists()

    def test_docker_compose_is_valid_yaml(self):
        import yaml

        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        parsed = yaml.safe_load(content)
        assert parsed is not None

    def test_docker_compose_has_services(self):
        import yaml

        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        parsed = yaml.safe_load(content)
        assert "services" in parsed

    def test_docker_compose_has_app_service(self):
        import yaml

        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        parsed = yaml.safe_load(content)
        assert "app" in parsed["services"]

    def test_docker_compose_has_healthcheck(self):
        import yaml

        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        parsed = yaml.safe_load(content)
        app_svc = parsed["services"]["app"]
        assert "healthcheck" in app_svc, "app service should have a healthcheck"

    def test_docker_compose_has_volumes(self):
        import yaml

        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        parsed = yaml.safe_load(content)
        # Either top-level volumes or service-level volumes
        has_volumes = "volumes" in parsed or "volumes" in parsed["services"].get("app", {})
        assert has_volumes

    def test_docker_compose_exposes_port_8765(self):
        import yaml

        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        parsed = yaml.safe_load(content)
        ports = parsed["services"]["app"].get("ports", [])
        port_strings = [str(p) for p in ports]
        assert any("8765" in p for p in port_strings)

    def test_dockerfile_exists(self):
        assert (DOCKER_DIR / "Dockerfile").exists()

    def test_dockerfile_has_healthcheck(self):
        content = (DOCKER_DIR / "Dockerfile").read_text()
        assert "HEALTHCHECK" in content

    def test_dockerfile_has_non_root_user(self):
        content = (DOCKER_DIR / "Dockerfile").read_text()
        assert "USER" in content

    def test_env_example_exists(self):
        assert (DOCKER_DIR / ".env.example").exists()

    def test_env_example_has_key_vars(self):
        content = (DOCKER_DIR / ".env.example").read_text()
        assert "AI_PROVIDER" in content
        assert "DEPLOY_MODE" in content
        assert "SESSION_SECRET" in content


class TestDockerProdConfig:
    def test_prod_compose_exists(self):
        assert (DOCKER_DIR / "docker-compose.prod.yml").exists()

    def test_prod_compose_is_valid_yaml(self):
        import yaml

        content = (DOCKER_DIR / "docker-compose.prod.yml").read_text()
        parsed = yaml.safe_load(content)
        assert parsed is not None


class TestDeployScript:
    def test_deploy_script_exists(self):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        assert (scripts_dir / "deploy.sh").exists()

    def test_deploy_script_is_executable_or_has_shebang(self):
        scripts_dir = Path(__file__).parent.parent / "scripts"
        content = (scripts_dir / "deploy.sh").read_text()
        assert content.startswith("#!")
