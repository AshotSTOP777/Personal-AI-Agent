from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus


async def create_job(
    session: AsyncSession, user_id: int, goal: str, next_run_at: dt.datetime | None = None
) -> Job:
    job = Job(
        user_id=user_id,
        goal=goal,
        status=JobStatus.ACTIVE,
        context={},
        next_run_at=next_run_at or dt.datetime.now(dt.timezone.utc),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def list_active_jobs(session: AsyncSession, user_id: int) -> list[Job]:
    stmt = (
        select(Job)
        .where(Job.user_id == user_id, Job.status.in_([JobStatus.ACTIVE, JobStatus.WAITING, JobStatus.PAUSED]))
        .order_by(Job.created_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_due_jobs(session: AsyncSession, max_runs: int, now: dt.datetime | None = None) -> list[Job]:
    now = now or dt.datetime.now(dt.timezone.utc)
    stmt = (
        select(Job)
        .where(
            Job.status.in_([JobStatus.ACTIVE, JobStatus.WAITING]),
            Job.next_run_at.is_not(None),
            Job.next_run_at <= now,
            Job.run_count < max_runs,
        )
        .order_by(Job.next_run_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_oldest_paused_job(session: AsyncSession, user_id: int) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.user_id == user_id, Job.status == JobStatus.PAUSED)
        .order_by(Job.updated_at.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_job(session: AsyncSession, job: Job, **fields: Any) -> Job:
    for key, value in fields.items():
        setattr(job, key, value)
    await session.commit()
    await session.refresh(job)
    return job


async def cancel_job(session: AsyncSession, user_id: int, job_id: int) -> Job | None:
    job = await get_job(session, job_id)
    if job is None or job.user_id != user_id or job.status in (JobStatus.DONE, JobStatus.FAILED):
        return None
    job.status = JobStatus.FAILED
    job.next_run_at = None
    await session.commit()
    await session.refresh(job)
    return job
