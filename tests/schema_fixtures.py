"""Reconstruct old schemas in tests that start from a current temporary database."""


def remove_project_groups(db):
    for name in (
        "group_history_remove",
        "group_history_delete",
        "group_task_delete",
        "group_input_delete",
    ):
        db.execute("DROP TRIGGER " + name)
    for name in ("project_group_requests", "project_group_links", "project_groups"):
        db.execute("DROP TABLE " + name)
