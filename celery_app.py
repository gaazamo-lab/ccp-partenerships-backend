"""
Celery application: the outbox relay and scheduled lifecycle sweeps.

Broker and result backend are Redis (`REDIS_URL`). Beat runs as its own process
so the schedule fires once, not once per worker replica.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery("partner-crm", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 3600},
    beat_schedule={
        "relay-outbox": {"task": "pcrm.relay_outbox", "schedule": 15.0},
        "partnership-lifecycle-sweep": {"task": "pcrm.partnership_sweep", "schedule": crontab(hour=5, minute=0)},
        "consultation-window-sweep": {"task": "pcrm.consultation_sweep", "schedule": 300.0},
        "correspondence-overdue-sweep": {"task": "pcrm.correspondence_sweep", "schedule": crontab(hour=6, minute=0)},
    },
)

celery.autodiscover_tasks(["app.tasks"], related_name="jobs")
