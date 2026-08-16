from __future__ import annotations

import asyncio
import signal

from app.schema_migrations.service import SchemaMigrationService

schema_migration_service = SchemaMigrationService()
schema_migration_service.assert_no_newer_versions()

from app.agents.bootstrap import (
    agent_manager,
)
from app.workflows.async_executor import (
    AsyncWorkflowExecutor,
)


async def run_worker() -> None:
    """
    Run the standalone workflow worker until
    SIGINT or SIGTERM requests graceful stop.
    """

    schema_migration_service.assert_runtime_compatible()

    executor = AsyncWorkflowExecutor(
        agent_manager,
        execution_mode="worker",
    )

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        stop_event.set()

    for signal_name in (
        signal.SIGINT,
        signal.SIGTERM,
    ):
        try:
            loop.add_signal_handler(
                signal_name,
                request_stop,
            )
        except NotImplementedError:
            signal.signal(
                signal_name,
                lambda *_: request_stop(),
            )

    worker_task = asyncio.create_task(
        executor.run_forever(),
        name=(
            "novelforge-standalone-"
            "workflow-worker"
        ),
    )

    stop_task = asyncio.create_task(
        stop_event.wait(),
        name=(
            "novelforge-worker-stop-"
            "signal"
        ),
    )

    done, pending = await asyncio.wait(
        {
            worker_task,
            stop_task,
        },
        return_when=(
            asyncio.FIRST_COMPLETED
        ),
    )

    _ = pending

    if worker_task in done:
        error = worker_task.exception()

        if error is not None:
            stop_task.cancel()

            await asyncio.gather(
                stop_task,
                return_exceptions=True,
            )

            raise error

    await executor.shutdown()

    stop_task.cancel()

    await asyncio.gather(
        worker_task,
        stop_task,
        return_exceptions=True,
    )


def main() -> None:

    try:
        asyncio.run(
            run_worker()
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
