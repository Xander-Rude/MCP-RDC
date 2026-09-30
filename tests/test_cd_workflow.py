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
