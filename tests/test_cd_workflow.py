from pathlib import Path


def test_cd_workflow_only_auto_deploys_main_push_from_this_repo():
    workflow = Path(".github/workflows/cd.yml").read_text(encoding="utf-8")

    required_guards = (
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.event.workflow_run.head_branch == 'main'",
    )

    for guard in required_guards:
        assert guard in workflow


def test_cd_uses_password_authentication():
    workflow = Path(".github/workflows/cd.yml").read_text(encoding="utf-8")

    assert "secrets.MCP_RDC_VPS_PASSWORD" in workflow
    assert "sshpass -e scp" in workflow
    assert "sshpass -e ssh" in workflow
    assert "MCP_RDC_VPS_SSH_KEY" not in workflow


def test_cd_does_not_depend_on_wireguard_interface():
    workflow = Path(".github/workflows/cd.yml").read_text(encoding="utf-8")

    assert "MCP_RDC_WG_INTERFACE" not in workflow
    assert "--wg-interface" not in workflow


def test_cd_bootstraps_caddy():
    workflow = Path(".github/workflows/cd.yml").read_text(encoding="utf-8")

    assert "--manage-caddy" in workflow
