from app import tasks


def test_knowledge_document_indexing_task_is_registered_by_tasks_package():
    assert hasattr(tasks, "index_knowledge_document_task")
    assert (
        "app.tasks.index_knowledge_document.index_knowledge_document_task"
        in tasks.celery_app.tasks
    )
